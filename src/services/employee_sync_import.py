"""Apply employee rows from a directory sync package (ADR-0010 Part 4b)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from data.db import Connection
from data.directories import (
    BranchRepository,
    DepartmentRepository,
    DivisionRepository,
    PositionRepository,
)
from data.employees import EmployeeRecord, EmployeeRepository
from data.repositories import UserActionLogRepository
from domain.directory_sync import DirectorySyncPackage
from domain.employee import EmployeeCreateInput
from domain.employee_reconciliation import (
    EmployeeMatchCandidate,
    EmployeeMatchStatus,
    EmployeeSyncApplyError,
    EmployeeSyncConflictDetail,
    EmployeeSyncConflictError,
)
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.employee_reconciliation import EmployeeReconciliationService
from services.employees import EmployeeService
from services.session import SessionState

Clock = Callable[[], str]

_SAVEPOINT = "employee_sync_apply"

_APPLYABLE = frozenset({EmployeeMatchStatus.EXACT, EmployeeMatchStatus.NEW})
_BLOCKING = frozenset(
    {
        EmployeeMatchStatus.CONFLICT,
        EmployeeMatchStatus.LOW,
        EmployeeMatchStatus.AMBIGUOUS,
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class _ResolvedSyncRow:
    external_id: str
    payload: EmployeeCreateInput
    hire_date: str | None
    contacts: str | None
    home_address: str | None
    social_insurance_number: str | None
    is_archived: bool


class EmployeeSyncImportService:
    """Validate and apply package employee rows after directory reconciliation."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        clock: Clock | None = None,
        authz: AuthorizationService | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._authz = authz or AuthorizationService()
        self._clock: Clock = clock or _utc_now
        self._employees = EmployeeRepository(conn)
        self._branches = BranchRepository(conn)
        self._departments = DepartmentRepository(conn)
        self._divisions = DivisionRepository(conn)
        self._positions = PositionRepository(conn)
        self._audit = UserActionLogRepository(conn)
        self._reconcile = EmployeeReconciliationService(conn, session, authz=self._authz)
        self._employee_service = EmployeeService(
            conn, session, authz=self._authz, clock=self._clock
        )

    def apply_employees(self, package: DirectorySyncPackage, *, commit: bool = True) -> None:
        rows = package.tables.get("employees", [])
        if not rows:
            return
        self._require_hr()
        if commit:
            self._conn.execute(f"SAVEPOINT {_SAVEPOINT}")
            try:
                self._apply_employees(package)
                self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                self._conn.commit()
            except (EmployeeSyncConflictError, EmployeeSyncApplyError):
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
                self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                raise
            except Exception:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
                self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                raise
        else:
            self._apply_employees(package)

    def _apply_employees(self, package: DirectorySyncPackage) -> None:
        rows = package.tables.get("employees", [])
        self._ensure_unique_external_ids(rows)
        matches = self._reconcile.build_reconciliation(package)
        self._reject_blocking_matches(matches)

        resolved: list[tuple[EmployeeMatchCandidate, _ResolvedSyncRow]] = []
        validation_errors: list[str] = []
        for match in matches:
            try:
                resolved.append((match, self._resolve_row(match.package_row)))
            except ValueError as exc:
                validation_errors.append(str(exc))
        if validation_errors:
            raise EmployeeSyncApplyError("; ".join(validation_errors))

        now = self._clock()
        can_edit_sensitive = self._authz.check(
            self._session.role, Permission.EDIT_SENSITIVE_EMPLOYEE_FIELDS
        )
        for match, row in resolved:
            if match.status == EmployeeMatchStatus.NEW:
                self._create_row(row, now=now, can_edit_sensitive=can_edit_sensitive)
            elif match.status == EmployeeMatchStatus.EXACT:
                assert match.matched_employee_id is not None
                local = self._employees.get(match.matched_employee_id)
                if local is None:
                    raise EmployeeSyncApplyError(
                        f"employee id {match.matched_employee_id} disappeared during apply"
                    )
                self._update_row(
                    local,
                    row,
                    now=now,
                    can_edit_sensitive=can_edit_sensitive,
                )

    def _create_row(
        self, row: _ResolvedSyncRow, *, now: str, can_edit_sensitive: bool
    ) -> None:
        home = row.home_address if can_edit_sensitive else None
        social = row.social_insurance_number if can_edit_sensitive else None
        employee_id = self._employees.create(
            external_id=row.external_id,
            full_name=row.payload.full_name,
            position_id=row.payload.position_id,
            branch_id=row.payload.branch_id,
            department_id=row.payload.department_id,
            division_id=row.payload.division_id,
            employment_type_id=row.payload.employment_type_id,
            note=row.payload.note,
            hire_date=row.hire_date,
            contacts=row.contacts,
            home_address=home,
            social_insurance_number=social,
            is_archived=row.is_archived,
            needs_org_review=False,
            created_at=now,
        )
        self._audit.record(
            account_id=self._session.account_id,
            action_type="employee.sync_create",
            result="success",
            created_at=now,
            entity_type="employee",
            entity_id=employee_id,
            details=f"external_id={row.external_id}",
        )

    def _update_row(
        self,
        local: EmployeeRecord,
        row: _ResolvedSyncRow,
        *,
        now: str,
        can_edit_sensitive: bool,
    ) -> None:
        home = row.home_address if can_edit_sensitive else local.home_address
        social = (
            row.social_insurance_number if can_edit_sensitive else local.social_insurance_number
        )
        if self._row_matches_local(local, row, home=home, social=social):
            return
        clear_review = local.needs_org_review
        self._employees.apply_sync_row(
            local.id,
            full_name=row.payload.full_name,
            position_id=row.payload.position_id,
            branch_id=row.payload.branch_id,
            department_id=row.payload.department_id,
            division_id=row.payload.division_id,
            employment_type_id=row.payload.employment_type_id,
            note=row.payload.note,
            hire_date=row.hire_date,
            contacts=row.contacts,
            home_address=home,
            social_insurance_number=social,
            is_archived=row.is_archived,
            clear_needs_org_review=clear_review,
            updated_at=now,
        )
        self._audit.record(
            account_id=self._session.account_id,
            action_type="employee.sync_update",
            result="success",
            created_at=now,
            entity_type="employee",
            entity_id=local.id,
            details=f"external_id={row.external_id}",
        )

    @staticmethod
    def _row_matches_local(
        local: EmployeeRecord,
        row: _ResolvedSyncRow,
        *,
        home: str | None,
        social: str | None,
    ) -> bool:
        payload = row.payload
        return (
            local.full_name == payload.full_name
            and local.position_id == payload.position_id
            and local.branch_id == payload.branch_id
            and local.department_id == payload.department_id
            and local.division_id == payload.division_id
            and local.employment_type_id == payload.employment_type_id
            and local.note == payload.note
            and local.hire_date == row.hire_date
            and local.contacts == row.contacts
            and local.home_address == home
            and local.social_insurance_number == social
            and local.is_archived == row.is_archived
        )

    def _resolve_row(self, package_row: dict[str, object]) -> _ResolvedSyncRow:
        external_id = str(package_row["external_id"])
        branch = self._branches.get_by_external_id(str(package_row["branch_external_id"]))
        if branch is None:
            raise ValueError(
                f"cannot resolve branch external_id {package_row['branch_external_id']!r}"
            )
        position = self._positions.get_by_external_id(str(package_row["position_external_id"]))
        if position is None:
            raise ValueError(
                f"cannot resolve position external_id {package_row['position_external_id']!r}"
            )
        department_id = self._resolve_optional_department(
            package_row.get("department_external_id"), branch_id=branch.id
        )
        division_id = self._resolve_optional_division(
            package_row.get("division_external_id"),
            branch_id=branch.id,
            department_id=department_id,
        )
        employment_type_id = int(package_row["employment_type_id"])
        note_raw = package_row.get("note")
        note = str(note_raw).strip() if note_raw else None
        if note == "":
            note = None
        hire_date = package_row.get("hire_date")
        hire_date_s = str(hire_date) if hire_date is not None else None
        contacts_raw = package_row.get("contacts")
        contacts = str(contacts_raw) if contacts_raw is not None else None
        home_raw = package_row.get("home_address")
        home = str(home_raw) if home_raw is not None else None
        social_raw = package_row.get("social_insurance_number")
        social = str(social_raw) if social_raw is not None else None
        payload = self._employee_service.validate_card_input(
            EmployeeCreateInput(
                full_name=str(package_row["full_name"]),
                position_id=position.id,
                branch_id=branch.id,
                department_id=department_id,
                division_id=division_id,
                employment_type_id=employment_type_id,
                note=note,
            )
        )
        return _ResolvedSyncRow(
            external_id=external_id,
            payload=payload,
            hire_date=hire_date_s,
            contacts=contacts,
            home_address=home,
            social_insurance_number=social,
            is_archived=bool(package_row.get("is_archived", False)),
        )

    def _resolve_optional_department(
        self, value: object, *, branch_id: int
    ) -> int | None:
        if value is None or value == "":
            return None
        record = self._departments.get_by_external_id(str(value))
        if record is None:
            raise ValueError(f"cannot resolve department external_id {value!r}")
        if record.branch_id != branch_id:
            raise ValueError(
                f"department external_id {value!r} belongs to another branch"
            )
        return record.id

    def _resolve_optional_division(
        self,
        value: object,
        *,
        branch_id: int,
        department_id: int | None,
    ) -> int | None:
        if value is None or value == "":
            return None
        record = self._divisions.get_by_external_id(str(value))
        if record is None:
            raise ValueError(f"cannot resolve division external_id {value!r}")
        if record.branch_id != branch_id:
            raise ValueError(f"division external_id {value!r} belongs to another branch")
        if record.department_id != department_id:
            raise ValueError(
                f"division external_id {value!r} is not under the resolved department"
            )
        return record.id

    @staticmethod
    def _ensure_unique_external_ids(rows: list[dict[str, object]]) -> None:
        seen: set[str] = set()
        for row in rows:
            external_id = str(row["external_id"])
            if external_id in seen:
                raise EmployeeSyncApplyError(
                    f"duplicate external_id in package: {external_id}"
                )
            seen.add(external_id)

    @staticmethod
    def _reject_blocking_matches(matches: list[EmployeeMatchCandidate]) -> None:
        blocked: list[EmployeeSyncConflictDetail] = []
        for match in matches:
            if match.status in _BLOCKING:
                blocked.append(
                    EmployeeSyncConflictDetail(
                        external_id=str(match.package_row["external_id"]),
                        full_name=str(match.package_row["full_name"]),
                        status=match.status,
                        matched_employee_id=match.matched_employee_id,
                    )
                )
            elif match.status not in _APPLYABLE:
                blocked.append(
                    EmployeeSyncConflictDetail(
                        external_id=str(match.package_row["external_id"]),
                        full_name=str(match.package_row["full_name"]),
                        status=match.status,
                        matched_employee_id=match.matched_employee_id,
                    )
                )
        if blocked:
            raise EmployeeSyncConflictError(blocked)

    def _require_hr(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)
        self._authz.require(self._session.role, Permission.MANAGE_EMPLOYEES)


__all__ = ["EmployeeSyncImportService"]
