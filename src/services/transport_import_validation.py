"""EPIC-020 slice 020-D: pre-DB transport package validation & confirmation gate.

Pure decision path: freshness/replay classification + directory/employee plan
builders. No SAVEPOINT, no commit, no transport-state advance, no apply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from data.db import Connection
from domain.directory_sync import DirectorySyncPackage
from domain.employee_reconciliation import EmployeeMatchStatus
from domain.permissions import Permission
from domain.transport import PackageClassification, TransportPackageMalformedError
from services.authorization import AuthorizationService
from services.directory_sync_import import DirectoryPlan, DirectorySyncImportService
from services.employee_sync_import import EmployeePlan, EmployeeSyncImportService
from services.session import SessionState
from services.transport_keys import TransportKeyStore
from services.transport_receive import DecryptedTransportPackage

_CONFIRMATION_STATUSES = frozenset(
    {EmployeeMatchStatus.LOW, EmployeeMatchStatus.AMBIGUOUS}
)
_HARD_REJECT_STATUSES = frozenset({EmployeeMatchStatus.CONFLICT})


class FreshnessClass(StrEnum):
    """Replay/freshness classification (ADR-0007); no side effects."""

    REPLAY = "replay"
    STALE = "stale"
    NEW = "new"


class ValidationDisposition(StrEnum):
    """What 020-E / UI should do next — not an apply action."""

    READY_FOR_APPLY = "ready_for_apply"
    REPLAY = "replay"
    REJECTED = "rejected"
    PENDING_CONFIRMATION = "pending_confirmation"


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of 020-D validation (plans only; never applied here)."""

    freshness: FreshnessClass
    disposition: ValidationDisposition
    directory_plan: DirectoryPlan | None
    employee_plan: EmployeePlan | None
    reject_reasons: tuple[str, ...] = ()
    confirmation_reasons: tuple[str, ...] = ()


class TransportImportValidationService:
    """Pre-DB validation gate for crypto-verified transport packages (020-D)."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        store: TransportKeyStore | None = None,
        authz: AuthorizationService | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._store = store or TransportKeyStore(conn)
        self._authz = authz or AuthorizationService()
        self._directories = DirectorySyncImportService(
            conn, session, authz=self._authz
        )
        self._employees = EmployeeSyncImportService(conn, session, authz=self._authz)

    def validate_package(
        self, decrypted: DecryptedTransportPackage
    ) -> ValidationResult:
        """Classify freshness, then build plans. Read-only; never applies."""
        self._require_import_export()
        freshness = self._classify_freshness(decrypted)
        if freshness is FreshnessClass.REPLAY:
            return ValidationResult(
                freshness=freshness,
                disposition=ValidationDisposition.REPLAY,
                directory_plan=None,
                employee_plan=None,
            )
        if freshness is FreshnessClass.STALE:
            return ValidationResult(
                freshness=freshness,
                disposition=ValidationDisposition.REJECTED,
                directory_plan=None,
                employee_plan=None,
                reject_reasons=("stale or out-of-sequence package",),
            )

        package = self._parse_payload(decrypted.payload)
        directory_plan = self._directories.build_directory_plan(package)
        if not directory_plan.is_clean:
            reasons = tuple(
                f"employee {emp_id} ({name}) would become invalid"
                for emp_id, name in directory_plan.broken_employees
            )
            return ValidationResult(
                freshness=freshness,
                disposition=ValidationDisposition.REJECTED,
                directory_plan=directory_plan,
                employee_plan=None,
                reject_reasons=reasons or ("directory plan rejected",),
            )

        employee_plan = self._employees.build_employee_plan(package, directory_plan)
        return self._disposition_from_employee_plan(
            freshness=freshness,
            directory_plan=directory_plan,
            employee_plan=employee_plan,
        )

    def _classify_freshness(
        self, decrypted: DecryptedTransportPackage
    ) -> FreshnessClass:
        """SELECT-only classification against transport_package_records / direction."""
        row = self._conn.execute(
            "SELECT classification FROM transport_package_records WHERE package_id = ?",
            (decrypted.package_id,),
        ).fetchone()
        if row is not None:
            if str(row[0]) == PackageClassification.ACCEPTED.value:
                return FreshnessClass.REPLAY
            return FreshnessClass.STALE

        direction = self._store.get_direction(decrypted.direction_id)
        max_row = self._conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM transport_package_records"
            " WHERE direction_id = ? AND classification = ?",
            (decrypted.direction_id, PackageClassification.ACCEPTED.value),
        ).fetchone()
        max_seq = int(max_row[0]) if max_row is not None else 0
        ceiling = max(direction.accepted_sequence, max_seq)
        if decrypted.sequence <= ceiling:
            return FreshnessClass.STALE
        return FreshnessClass.NEW

    @staticmethod
    def _parse_payload(payload: bytes) -> DirectorySyncPackage:
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportPackageMalformedError(
                f"payload is not UTF-8 JSON: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise TransportPackageMalformedError(
                "payload JSON must be an object of table → rows"
            )
        tables: dict[str, list[dict[str, object]]] = {}
        for key, rows in raw.items():
            if not isinstance(key, str) or not isinstance(rows, list):
                raise TransportPackageMalformedError(
                    "payload table entries must be list-of-objects"
                )
            tables[key] = [row for row in rows if isinstance(row, dict)]
        return DirectorySyncPackage(tables=tables)

    @staticmethod
    def _disposition_from_employee_plan(
        *,
        freshness: FreshnessClass,
        directory_plan: DirectoryPlan,
        employee_plan: EmployeePlan,
    ) -> ValidationResult:
        if employee_plan.validation_errors:
            return ValidationResult(
                freshness=freshness,
                disposition=ValidationDisposition.REJECTED,
                directory_plan=directory_plan,
                employee_plan=employee_plan,
                reject_reasons=tuple(employee_plan.validation_errors),
            )

        hard: list[str] = []
        confirm: list[str] = []
        for detail in employee_plan.conflicts:
            msg = (
                f"{detail.status.value}: external_id={detail.external_id} "
                f"name={detail.full_name!r}"
            )
            if detail.status in _HARD_REJECT_STATUSES:
                hard.append(msg)
            elif detail.status in _CONFIRMATION_STATUSES:
                confirm.append(msg)
            else:
                hard.append(msg)

        if hard:
            return ValidationResult(
                freshness=freshness,
                disposition=ValidationDisposition.REJECTED,
                directory_plan=directory_plan,
                employee_plan=employee_plan,
                reject_reasons=tuple(hard),
                confirmation_reasons=tuple(confirm),
            )
        if confirm:
            return ValidationResult(
                freshness=freshness,
                disposition=ValidationDisposition.PENDING_CONFIRMATION,
                directory_plan=directory_plan,
                employee_plan=employee_plan,
                confirmation_reasons=tuple(confirm),
            )
        return ValidationResult(
            freshness=freshness,
            disposition=ValidationDisposition.READY_FOR_APPLY,
            directory_plan=directory_plan,
            employee_plan=employee_plan,
        )

    def _require_import_export(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)


__all__ = [
    "FreshnessClass",
    "TransportImportValidationService",
    "ValidationDisposition",
    "ValidationResult",
]
