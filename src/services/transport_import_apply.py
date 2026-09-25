"""EPIC-020 slice 020-E: atomic apply for validated inbound transport packages.

Single transaction owner for directory + employee writes, package acceptance,
WK rotation, and audit. Crypto, validation, and confirmation run before BEGIN.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from data.db import Connection
from data.repositories import UserActionLogRepository
from domain.employee_reconciliation import EmployeeMatchStatus
from domain.permissions import Permission
from domain.transport import (
    ENTITY_TRANSPORT,
    PackageClassification,
    TransportApplyNotReadyError,
    TransportKeyError,
    WkRole,
)
from services.authorization import AuthorizationService
from services.directory_sync_import import DirectoryPlan, DirectorySyncImportService
from services.employee_sync_import import EmployeePlan, EmployeeSyncImportService
from services.session import SessionState
from services.transport_import_validation import ValidationDisposition, ValidationResult
from services.transport_keys import TransportKeyStore
from services.transport_receive import DecryptedTransportPackage

Clock = Callable[[], str]


@dataclass(frozen=True)
class ApplyDirectoryStats:
    creates: int
    updates: int


@dataclass(frozen=True)
class ApplyEmployeeStats:
    creates: int
    updates: int


@dataclass(frozen=True)
class ApplyResult:
    package_id: str
    direction_id: int
    sequence: int
    classification: PackageClassification
    directory_stats: ApplyDirectoryStats | None = None
    employee_stats: ApplyEmployeeStats | None = None


def _directory_stats(plan: DirectoryPlan) -> ApplyDirectoryStats:
    creates = (
        len(plan.branch_creates)
        + len(plan.department_creates)
        + len(plan.division_creates)
        + len(plan.position_creates)
    )
    updates = (
        len(plan.branch_updates)
        + len(plan.department_updates)
        + len(plan.division_updates)
        + len(plan.position_updates)
    )
    return ApplyDirectoryStats(creates=creates, updates=updates)


def _employee_stats(plan: EmployeePlan) -> ApplyEmployeeStats:
    creates = sum(
        1 for item in plan.items if item.match.status is EmployeeMatchStatus.NEW
    )
    updates = sum(
        1 for item in plan.items if item.match.status is EmployeeMatchStatus.EXACT
    )
    return ApplyEmployeeStats(creates=creates, updates=updates)


class TransportImportApplyService:
    """Orchestrator-owned atomic apply for READY_FOR_APPLY packages (020-E)."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        store: TransportKeyStore | None = None,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._store = store or TransportKeyStore(conn, clock=clock)
        self._authz = authz or AuthorizationService()
        self._clock = self._store._clock  # noqa: SLF001
        self._directories = DirectorySyncImportService(
            conn, session, clock=clock, authz=self._authz
        )
        self._employees = EmployeeSyncImportService(
            conn, session, clock=clock, authz=self._authz
        )
        self._audit = UserActionLogRepository(conn)

    def apply_validated_package(
        self,
        decrypted: DecryptedTransportPackage,
        validation: ValidationResult,
    ) -> ApplyResult:
        """Apply business + transport state in one commit; rollback on any error."""
        self._require_import_export()
        self._guard_ready(decrypted, validation)
        directory_plan = validation.directory_plan
        employee_plan = validation.employee_plan
        assert directory_plan is not None and employee_plan is not None

        dir_stats = _directory_stats(directory_plan)
        emp_stats = _employee_stats(employee_plan)
        now = self._clock()

        try:
            self._directories.apply_directory_plan(directory_plan, commit=False)
            self._employees.apply_employee_plan(employee_plan, commit=False)
            self._apply_status_history_from_payload(decrypted)
            self._persist_package_acceptance(decrypted, now=now)
            self._advance_transport_state(decrypted, now=now)
            self._audit.record(
                account_id=self._session.account_id,
                action_type="transport.package.apply",
                entity_type=ENTITY_TRANSPORT,
                entity_id=decrypted.direction_id,
                result="success",
                details=(
                    f"package_id={decrypted.package_id} sequence={decrypted.sequence}"
                    f" direction_id={decrypted.direction_id}"
                    f" directory_creates={dir_stats.creates}"
                    f" directory_updates={dir_stats.updates}"
                    f" employee_creates={emp_stats.creates}"
                    f" employee_updates={emp_stats.updates}"
                ),
                created_at=now,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return ApplyResult(
            package_id=decrypted.package_id,
            direction_id=decrypted.direction_id,
            sequence=decrypted.sequence,
            classification=PackageClassification.ACCEPTED,
            directory_stats=dir_stats,
            employee_stats=emp_stats,
        )

    def _apply_status_history_from_payload(
        self, decrypted: DecryptedTransportPackage
    ) -> None:
        """No-op when payload has no status tables (current transport export scope)."""

    def _persist_package_acceptance(
        self, decrypted: DecryptedTransportPackage, *, now: str
    ) -> None:
        repo = self._store._repo  # noqa: SLF001
        existing = repo.find_package(decrypted.package_id)
        if existing is not None:
            raise TransportKeyError(f"package_id already used: {decrypted.package_id}")
        max_seq = repo.max_accepted_sequence(decrypted.direction_id)
        if decrypted.sequence <= max_seq:
            raise TransportKeyError("stale or consumed sequence")
        repo.insert_package_record(
            direction_id=decrypted.direction_id,
            package_id=decrypted.package_id,
            sequence=decrypted.sequence,
            classification=PackageClassification.ACCEPTED,
            envelope_key_id=decrypted.envelope_key_id,
            rejection_reason=None,
            now=now,
            accepted_at=now,
        )

    def _advance_transport_state(
        self, decrypted: DecryptedTransportPackage, *, now: str
    ) -> None:
        repo = self._store._repo  # noqa: SLF001
        current = self._store.get_current_wk(decrypted.direction_id)
        predecessor = current.key_id if current is not None else None
        if repo.wire_key_id_exists(decrypted.next_wk_key_id):
            raise TransportKeyError(
                f"wire key_id collision: {decrypted.next_wk_key_id}"
            )
        wk_row_id = repo.insert_wk_key(
            key_id=decrypted.next_wk_key_id,
            direction_id=decrypted.direction_id,
            wk_key_material=decrypted.next_wk_material,
            wk_role=WkRole.HISTORICAL,
            sequence_established=None,
            predecessor_key_id=predecessor,
            now=now,
        )
        self._store.activate_wk_for_direction(
            direction_id=decrypted.direction_id,
            wk_row_id=wk_row_id,
            accepted_sequence=decrypted.sequence,
        )

    def _guard_ready(
        self, decrypted: DecryptedTransportPackage, validation: ValidationResult
    ) -> None:
        if validation.disposition is not ValidationDisposition.READY_FOR_APPLY:
            raise TransportApplyNotReadyError(
                f"disposition is {validation.disposition.value}, not ready_for_apply"
            )
        if validation.directory_plan is None or validation.employee_plan is None:
            raise TransportApplyNotReadyError("validation plans are missing")
        if not validation.directory_plan.is_clean:
            raise TransportApplyNotReadyError("directory plan is not clean")
        if not validation.employee_plan.is_clean:
            raise TransportApplyNotReadyError("employee plan is not clean")

        repo = self._store._repo  # noqa: SLF001
        existing = repo.find_package(decrypted.package_id)
        if (
            existing is not None
            and existing.classification is PackageClassification.ACCEPTED
        ):
            raise TransportApplyNotReadyError(
                f"package already accepted: {decrypted.package_id}"
            )

        direction = self._store.get_direction(decrypted.direction_id)
        max_seq = repo.max_accepted_sequence(decrypted.direction_id)
        ceiling = max(direction.accepted_sequence, max_seq)
        if decrypted.sequence <= ceiling:
            raise TransportApplyNotReadyError("stale or out-of-sequence package")

    def _require_import_export(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)


class TransportImportApplyAdminService:
    """Authorized apply facade (IMPORT_EXPORT gate); delegates to core orchestrator."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        store: TransportKeyStore | None = None,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._apply = TransportImportApplyService(
            conn,
            session,
            store=store,
            authz=authz,
            clock=clock,
        )

    def apply_validated_package(
        self,
        decrypted: DecryptedTransportPackage,
        validation: ValidationResult,
    ) -> ApplyResult:
        return self._apply.apply_validated_package(decrypted, validation)


__all__ = [
    "ApplyDirectoryStats",
    "ApplyEmployeeStats",
    "ApplyResult",
    "TransportImportApplyAdminService",
    "TransportImportApplyService",
]
