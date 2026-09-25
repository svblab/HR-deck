"""Apply employee rows from a directory sync package (ADR-0010 Part 4b).

Plan/apply split (ADR-0010 addendum): ``build_employee_plan`` is pure
(no writes); ``apply_employee_plan`` performs writes. ``apply_employees``
is a thin build+apply wrapper for existing callers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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
from domain.employee import (
    EmployeeCreateInput,
    EmployeeValidationError,
    clean_full_name,
    validate_employee_org,
)
from domain.employee_reconciliation import (
    EmployeeMatchCandidate,
    EmployeeMatchStatus,
    EmployeeSyncApplyError,
    EmployeeSyncConflictDetail,
    EmployeeSyncConflictError,
)
from domain.org_structure import (
    DepartmentRef,
    DivisionRef,
    validate_position_branch,
    validate_position_requirements,
)
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.employee_reconciliation import EmployeeReconciliationService
from services.employees import EmployeeError, EmployeeService
from services.session import SessionState

if TYPE_CHECKING:
    from services.directory_sync_import import DirectoryPlan

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


@dataclass(frozen=True)
class _EmployeePlanItem:
    match: EmployeeMatchCandidate
    # package_row kept for apply-time re-resolve against DB after directory writes.
    package_row: dict[str, object]


@dataclass
class EmployeePlan:
    """Pure employee apply plan (no DB writes performed to produce it)."""

    items: list[_EmployeePlanItem] = field(default_factory=list)
    conflicts: list[EmployeeSyncConflictDetail] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.conflicts and not self.validation_errors


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

    def build_employee_plan(
        self,
        package: DirectorySyncPackage,
        directory_plan: DirectoryPlan | None = None,
    ) -> EmployeePlan:
        """Pure: classification + projected resolve. No SAVEPOINT, no writes."""
        self._require_hr()
        rows = package.tables.get("employees", [])
        plan = EmployeePlan()
        if not rows:
            return plan
        try:
            self._ensure_unique_external_ids(rows)
        except EmployeeSyncApplyError as exc:
            plan.validation_errors.append(str(exc))
            return plan

        matches = self._reconcile.build_reconciliation(package)
        conflicts = self._collect_blocking_matches(matches)
        if conflicts:
            plan.conflicts = conflicts
            return plan

        for match in matches:
            try:
                self._validate_row_projected(match.package_row, directory_plan)
            except ValueError as exc:
                plan.validation_errors.append(str(exc))
                continue
            except EmployeeError as exc:
                plan.validation_errors.append(str(exc))
                continue
            plan.items.append(_EmployeePlanItem(match=match, package_row=match.package_row))
        return plan

    def apply_employee_plan(self, plan: EmployeePlan, *, commit: bool = True) -> None:
        """Write employee ops from an already-built plan."""
        self._require_hr()
        if plan.conflicts:
            raise EmployeeSyncConflictError(list(plan.conflicts))
        if plan.validation_errors:
            raise EmployeeSyncApplyError("; ".join(plan.validation_errors))
        if not plan.items:
            return

        def _write() -> None:
            now = self._clock()
            can_edit_sensitive = self._authz.check(
                self._session.role, Permission.EDIT_SENSITIVE_EMPLOYEE_FIELDS
            )
            for item in plan.items:
                row = self._resolve_row(item.package_row)
                if item.match.status == EmployeeMatchStatus.NEW:
                    self._create_row(row, now=now, can_edit_sensitive=can_edit_sensitive)
                elif item.match.status == EmployeeMatchStatus.EXACT:
                    assert item.match.matched_employee_id is not None
                    local = self._employees.get(item.match.matched_employee_id)
                    if local is None:
                        raise EmployeeSyncApplyError(
                            f"employee id {item.match.matched_employee_id} "
                            "disappeared during apply"
                        )
                    self._update_row(
                        local,
                        row,
                        now=now,
                        can_edit_sensitive=can_edit_sensitive,
                    )

        if commit:
            self._conn.execute(f"SAVEPOINT {_SAVEPOINT}")
            try:
                _write()
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
            _write()

    def apply_employees(self, package: DirectorySyncPackage, *, commit: bool = True) -> None:
        """Thin wrapper: build plan then apply (preserves Part 4b callers)."""
        rows = package.tables.get("employees", [])
        if not rows:
            return
        plan = self.build_employee_plan(package, directory_plan=None)
        if plan.conflicts:
            raise EmployeeSyncConflictError(list(plan.conflicts))
        if plan.validation_errors:
            raise EmployeeSyncApplyError("; ".join(plan.validation_errors))
        self.apply_employee_plan(plan, commit=commit)

    def _validate_row_projected(
        self,
        package_row: dict[str, object],
        directory_plan: DirectoryPlan | None,
    ) -> None:
        """Validate org refs using directory plan projection when provided."""
        branch_ext = str(package_row["branch_external_id"])
        pos_ext = str(package_row["position_external_id"])
        branch_id, branch_archived = self._lookup_branch(branch_ext, directory_plan)
        position_id, pos = self._lookup_position(pos_ext, directory_plan)
        if branch_archived:
            raise ValueError(f"archived branch cannot be assigned ({branch_ext!r})")
        if pos.is_archived:
            raise ValueError(f"archived position cannot be assigned ({pos_ext!r})")
        department_id, dept = self._lookup_optional_department(
            package_row.get("department_external_id"),
            branch_id=branch_id,
            directory_plan=directory_plan,
        )
        division_id, div = self._lookup_optional_division(
            package_row.get("division_external_id"),
            branch_id=branch_id,
            department_id=department_id,
            directory_plan=directory_plan,
        )
        employment_type_id = int(package_row["employment_type_id"])
        # Employment types are seed data; validate via service when IDs are real.
        # Provisional directory ids (<0) skip DB getters; use domain validators.
        note_raw = package_row.get("note")
        note = str(note_raw).strip() if note_raw else None
        if note == "":
            note = None
        full_name = clean_full_name(str(package_row["full_name"]))
        try:
            validate_employee_org(
                branch_id=branch_id,
                department_id=department_id,
                division_id=division_id,
                department=(
                    DepartmentRef(id=dept.id, branch_id=dept.branch_id) if dept else None
                ),
                division=(
                    DivisionRef(
                        id=div.id,
                        branch_id=div.branch_id,
                        department_id=div.department_id,
                    )
                    if div
                    else None
                ),
            )
            validate_position_requirements(
                department_id=department_id,
                division_id=division_id,
                department_required=pos.department_required,
                division_required=pos.division_required,
            )
            validate_position_branch(
                employee_branch_id=branch_id,
                position_branch_id=pos.branch_id,
            )
        except EmployeeValidationError as exc:
            raise EmployeeError(str(exc)) from exc
        if branch_id > 0 and position_id > 0:
            # Real DB ids: also run service validation (employment type, etc.).
            dept_arg = (
                department_id
                if department_id is None or department_id > 0
                else None
            )
            div_arg = (
                division_id if division_id is None or division_id > 0 else None
            )
            self._employee_service.validate_card_input(
                EmployeeCreateInput(
                    full_name=full_name,
                    position_id=position_id,
                    branch_id=branch_id,
                    department_id=dept_arg,
                    division_id=div_arg,
                    employment_type_id=employment_type_id,
                    note=note,
                )
            )

    def _lookup_branch(
        self, external_id: str, directory_plan: DirectoryPlan | None
    ) -> tuple[int, bool]:
        if directory_plan is not None and external_id in directory_plan.branch_ids:
            bid = directory_plan.branch_ids[external_id]
            rec = directory_plan.projected_branches[bid]
            return bid, rec.is_archived
        record = self._branches.get_by_external_id(external_id)
        if record is None:
            raise ValueError(f"cannot resolve branch external_id {external_id!r}")
        return record.id, record.is_archived

    def _lookup_position(
        self, external_id: str, directory_plan: DirectoryPlan | None
    ):
        if directory_plan is not None and external_id in directory_plan.position_ids:
            pid = directory_plan.position_ids[external_id]
            return pid, directory_plan.projected_positions[pid]
        record = self._positions.get_by_external_id(external_id)
        if record is None:
            raise ValueError(f"cannot resolve position external_id {external_id!r}")
        return record.id, record

    def _lookup_optional_department(
        self,
        value: object,
        *,
        branch_id: int,
        directory_plan: DirectoryPlan | None,
    ):
        if value is None or value == "":
            return None, None
        ext = str(value)
        if directory_plan is not None and ext in directory_plan.department_ids:
            did = directory_plan.department_ids[ext]
            rec = directory_plan.projected_departments[did]
            if rec.branch_id != branch_id:
                raise ValueError(f"department external_id {ext!r} belongs to another branch")
            if rec.is_archived:
                raise ValueError(f"archived department cannot be assigned ({ext!r})")
            return did, rec
        record = self._departments.get_by_external_id(ext)
        if record is None:
            raise ValueError(f"cannot resolve department external_id {ext!r}")
        if record.branch_id != branch_id:
            raise ValueError(f"department external_id {ext!r} belongs to another branch")
        return record.id, record

    def _lookup_optional_division(
        self,
        value: object,
        *,
        branch_id: int,
        department_id: int | None,
        directory_plan: DirectoryPlan | None,
    ):
        if value is None or value == "":
            return None, None
        ext = str(value)
        if directory_plan is not None and ext in directory_plan.division_ids:
            vid = directory_plan.division_ids[ext]
            rec = directory_plan.projected_divisions[vid]
            if rec.branch_id != branch_id:
                raise ValueError(f"division external_id {ext!r} belongs to another branch")
            if rec.department_id != department_id:
                raise ValueError(
                    f"division external_id {ext!r} is not under the resolved department"
                )
            if rec.is_archived:
                raise ValueError(f"archived division cannot be assigned ({ext!r})")
            return vid, rec
        record = self._divisions.get_by_external_id(ext)
        if record is None:
            raise ValueError(f"cannot resolve division external_id {ext!r}")
        if record.branch_id != branch_id:
            raise ValueError(f"division external_id {ext!r} belongs to another branch")
        if record.department_id != department_id:
            raise ValueError(
                f"division external_id {ext!r} is not under the resolved department"
            )
        return record.id, record

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
        fields_match = self._row_matches_local(local, row, home=home, social=social)
        if fields_match and not local.needs_org_review:
            return
        if fields_match and local.needs_org_review:
            self._employees.clear_needs_org_review(local.id, updated_at=now)
            self._audit.record(
                account_id=self._session.account_id,
                action_type="employee.sync_update",
                result="success",
                created_at=now,
                entity_type="employee",
                entity_id=local.id,
                details=f"external_id={row.external_id};cleared_needs_org_review=1",
            )
            return
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
            clear_needs_org_review=local.needs_org_review,
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
    def _collect_blocking_matches(
        matches: list[EmployeeMatchCandidate],
    ) -> list[EmployeeSyncConflictDetail]:
        blocked: list[EmployeeSyncConflictDetail] = []
        for match in matches:
            if match.status in _BLOCKING or match.status not in _APPLYABLE:
                blocked.append(
                    EmployeeSyncConflictDetail(
                        external_id=str(match.package_row["external_id"]),
                        full_name=str(match.package_row["full_name"]),
                        status=match.status,
                        matched_employee_id=match.matched_employee_id,
                    )
                )
        return blocked

    def _require_hr(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)
        self._authz.require(self._session.role, Permission.MANAGE_EMPLOYEES)


__all__ = ["EmployeePlan", "EmployeeSyncImportService"]
