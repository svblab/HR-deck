"""CRUD карточки сотрудника: RBAC, аудит, маскирование чувствительных полей (EPIC-005)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from data.db import Connection
from data.directories import (
    BranchRepository,
    DepartmentRepository,
    DivisionRepository,
    EmploymentTypeRepository,
    PositionRepository,
)
from data.employees import EmployeeRecord, EmployeeRepository
from data.repositories import UserActionLogRepository
from domain.employee import (
    EmployeeCard,
    EmployeeCreateInput,
    EmployeeSearchHit,
    EmployeeUpdateInput,
    EmployeeValidationError,
    SensitiveEmployeeInput,
    clean_full_name,
    validate_employee_org,
)
from domain.org_structure import DepartmentRef, DivisionRef
from domain.permissions import Permission
from domain.sensitive import mask_sensitive_value
from services.authorization import AuthorizationError, AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class EmployeeError(Exception):
    """Ошибка операции с карточкой сотрудника."""


class EmployeeService:
    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._authz = authz or AuthorizationService()
        self._clock: Clock = clock or _utc_now
        self._audit = UserActionLogRepository(conn)
        self._employees = EmployeeRepository(conn)
        self._branches = BranchRepository(conn)
        self._departments = DepartmentRepository(conn)
        self._divisions = DivisionRepository(conn)
        self._positions = PositionRepository(conn)
        self._employment_types = EmploymentTypeRepository(conn)

    def create_employee(self, data: EmployeeCreateInput) -> int:
        self._require(Permission.MANAGE_EMPLOYEES)
        payload = self._validate_input(data)
        now = self._clock()
        return self._mutate(
            action="employee.create",
            entity_type="employee",
            mutate=lambda: self._employees.create(
                full_name=payload.full_name,
                position_id=payload.position_id,
                branch_id=payload.branch_id,
                department_id=payload.department_id,
                employment_type_id=payload.employment_type_id,
                division_id=payload.division_id,
                note=payload.note,
                created_at=now,
            ),
            details=self._details(payload),
        )

    def get_employee(self, employee_id: int) -> EmployeeCard:
        self._require(Permission.VIEW_EMPLOYEES)
        record = self._require_employee(employee_id)
        can_view_sensitive = self._authz.check(
            self._session.role, Permission.VIEW_SENSITIVE_EMPLOYEE_FIELDS
        )
        if can_view_sensitive and self._has_sensitive_values(record):
            self._audit_sensitive_view(employee_id)
        return self._to_card(record, mask_sensitive=not can_view_sensitive)

    def update_employee(self, employee_id: int, data: EmployeeUpdateInput) -> None:
        self._require(Permission.MANAGE_EMPLOYEES)
        self._require_active_employee(employee_id)
        payload = self._validate_input(data)
        now = self._clock()
        self._mutate(
            action="employee.update",
            entity_type="employee",
            entity_id=employee_id,
            mutate=lambda: self._employees.update(
                employee_id,
                full_name=payload.full_name,
                position_id=payload.position_id,
                branch_id=payload.branch_id,
                department_id=payload.department_id,
                employment_type_id=payload.employment_type_id,
                division_id=payload.division_id,
                note=payload.note,
                updated_at=now,
            ),
            details=self._details(payload),
        )

    def update_sensitive_fields(
        self, employee_id: int, data: SensitiveEmployeeInput
    ) -> None:
        self._require(Permission.EDIT_SENSITIVE_EMPLOYEE_FIELDS)
        self._require_active_employee(employee_id)
        now = self._clock()
        self._mutate(
            action="employee.update_sensitive",
            entity_type="employee",
            entity_id=employee_id,
            mutate=lambda: self._employees.update_sensitive(
                employee_id,
                home_address=data.home_address,
                social_insurance_number=data.social_insurance_number,
                updated_at=now,
            ),
            details="sensitive_fields=1",
        )

    def search_by_name(self, prefix: str, *, limit: int = 50) -> list[EmployeeSearchHit]:
        self._require(Permission.VIEW_EMPLOYEES)
        clean = prefix.strip()
        if not clean:
            return []
        records = self._employees.search_by_name(clean, limit=limit)
        return [self._to_search_hit(r) for r in records]

    def list_employees(self, *, active_only: bool = True) -> list[EmployeeCard]:
        self._require(Permission.VIEW_EMPLOYEES)
        can_view_sensitive = self._authz.check(
            self._session.role, Permission.VIEW_SENSITIVE_EMPLOYEE_FIELDS
        )
        return [
            self._to_card(r, mask_sensitive=not can_view_sensitive)
            for r in self._employees.list(active_only=active_only)
        ]

    def archive_employee(self, employee_id: int) -> None:
        self._set_archived(employee_id, archived=True)

    def restore_employee(self, employee_id: int) -> None:
        self._set_archived(employee_id, archived=False)

    def _set_archived(self, employee_id: int, *, archived: bool) -> None:
        self._require(Permission.MANAGE_EMPLOYEES)
        record = self._require_employee(employee_id)
        if record.is_archived == archived:
            return
        now = self._clock()
        verb = "archive" if archived else "restore"
        self._mutate(
            action=f"employee.{verb}",
            entity_type="employee",
            entity_id=employee_id,
            mutate=lambda: self._employees.set_archived(
                employee_id, archived=archived, updated_at=now
            ),
        )

    def _validate_input(
        self, data: EmployeeCreateInput | EmployeeUpdateInput
    ) -> EmployeeCreateInput:
        full_name = clean_full_name(data.full_name)
        self._require_active_directory(self._positions.get, data.position_id, "position")
        self._require_active_directory(self._branches.get, data.branch_id, "branch")
        department = self._require_active_directory(
            self._departments.get, data.department_id, "department"
        )
        division = None
        if data.division_id is not None:
            division = self._require_active_directory(
                self._divisions.get, data.division_id, "division"
            )
        self._require_active_directory(
            self._employment_types.get, data.employment_type_id, "employment_type"
        )
        try:
            validate_employee_org(
                branch_id=data.branch_id,
                department_id=data.department_id,
                division_id=data.division_id,
                department=DepartmentRef(id=department.id, branch_id=department.branch_id),
                division=(
                    DivisionRef(id=division.id, department_id=division.department_id)
                    if division
                    else None
                ),
            )
        except EmployeeValidationError as exc:
            raise EmployeeError(str(exc)) from exc
        return EmployeeCreateInput(
            full_name=full_name,
            position_id=data.position_id,
            branch_id=data.branch_id,
            department_id=data.department_id,
            employment_type_id=data.employment_type_id,
            division_id=data.division_id,
            note=data.note.strip() if data.note else None,
        )

    def _require_active_directory(self, getter, entity_id: int, label: str):
        row = getter(entity_id)
        if row is None:
            raise EmployeeError(f"{label} not found")
        if row.is_archived:
            raise EmployeeError(f"archived {label} cannot be assigned")
        return row

    def _to_card(self, record: EmployeeRecord, *, mask_sensitive: bool) -> EmployeeCard:
        home = record.home_address
        social = record.social_insurance_number
        masked = mask_sensitive
        if mask_sensitive:
            home = mask_sensitive_value(home)
            social = mask_sensitive_value(social)
        return EmployeeCard(
            id=record.id,
            full_name=record.full_name,
            position_id=record.position_id,
            branch_id=record.branch_id,
            department_id=record.department_id,
            division_id=record.division_id,
            employment_type_id=record.employment_type_id,
            note=record.note,
            home_address=home,
            social_insurance_number=social,
            sensitive_fields_masked=masked
            and (
                record.home_address is not None or record.social_insurance_number is not None
            ),
            is_archived=record.is_archived,
        )

    def _to_search_hit(self, record: EmployeeRecord) -> EmployeeSearchHit:
        position = self._positions.get(record.position_id)
        branch = self._branches.get(record.branch_id)
        department = self._departments.get(record.department_id)
        division = (
            self._divisions.get(record.division_id) if record.division_id is not None else None
        )
        return EmployeeSearchHit(
            id=record.id,
            full_name=record.full_name,
            position_name=position.name if position else "",
            branch_name=branch.name if branch else "",
            department_name=department.name if department else "",
            division_name=division.name if division else None,
            hire_date=record.hire_date,
        )

    def _has_sensitive_values(self, record: EmployeeRecord) -> bool:
        return bool(record.home_address or record.social_insurance_number)

    def _audit_sensitive_view(self, employee_id: int) -> None:
        now = self._clock()
        self._audit.record(
            account_id=self._session.account_id,
            action_type="employee.view_sensitive",
            result="success",
            created_at=now,
            entity_type="employee",
            entity_id=employee_id,
        )
        self._conn.commit()

    def _require(self, permission: Permission) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, permission)

    def _require_employee(self, employee_id: int) -> EmployeeRecord:
        record = self._employees.get(employee_id)
        if record is None:
            raise EmployeeError("employee not found")
        return record

    def _require_active_employee(self, employee_id: int) -> EmployeeRecord:
        record = self._require_employee(employee_id)
        if record.is_archived:
            raise EmployeeError("archived employee cannot be modified")
        return record

    def _mutate(
        self,
        *,
        action: str,
        entity_type: str,
        mutate: Callable[[], int | None],
        entity_id: int | None = None,
        details: str | None = None,
    ) -> int:
        now = self._clock()
        try:
            result = mutate()
            new_id = int(result) if result is not None else entity_id
            if new_id is None:
                raise EmployeeError("mutation did not yield entity id")
            self._audit.record(
                account_id=self._session.account_id,
                action_type=action,
                result="success",
                created_at=now,
                entity_type=entity_type,
                entity_id=new_id,
                details=details,
            )
            self._conn.commit()
            return new_id
        except Exception:
            self._conn.rollback()
            raise

    @staticmethod
    def _details(data: EmployeeCreateInput) -> str:
        parts = [
            f"position_id={data.position_id}",
            f"branch_id={data.branch_id}",
            f"department_id={data.department_id}",
        ]
        if data.division_id is not None:
            parts.append(f"division_id={data.division_id}")
        return ";".join(parts)


__all__ = ["AuthorizationError", "EmployeeError", "EmployeeService"]
