"""CRUD справочников с RBAC и атомарным аудитом (EPIC-004)."""

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
from data.repositories import UserActionLogRepository
from domain.permissions import Permission
from services.authorization import AuthorizationError, AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DirectoryError(Exception):
    """Ошибка операции со справочником."""


class DirectoryService:
    """Справочники оргструктуры: филиал → департамент → отдел + должности и типы занятости."""

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
        self._branches = BranchRepository(conn)
        self._departments = DepartmentRepository(conn)
        self._divisions = DivisionRepository(conn)
        self._positions = PositionRepository(conn)
        self._employment_types = EmploymentTypeRepository(conn)

    # --- Branches ---

    def list_branches(self, *, active_only: bool = False):
        self._require(Permission.VIEW_DIRECTORIES)
        return self._branches.list(active_only=active_only)

    def create_branch(self, name: str) -> int:
        self._require(Permission.MANAGE_DIRECTORIES)
        clean = _clean_name(name)
        now = self._clock()
        return self._mutate(
            action="directory.branch.create",
            entity_type="branch",
            mutate=lambda: self._branches.create(name=clean, created_at=now),
            details=f"name={clean}",
        )

    def rename_branch(self, branch_id: int, name: str) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_branch(branch_id)
        clean = _clean_name(name)
        now = self._clock()
        self._mutate(
            action="directory.branch.rename",
            entity_type="branch",
            entity_id=branch_id,
            mutate=lambda: self._branches.rename(branch_id, name=clean, updated_at=now),
            details=f"name={clean}",
        )

    def archive_branch(self, branch_id: int) -> None:
        self._set_branch_archived(branch_id, archived=True)

    def unarchive_branch(self, branch_id: int) -> None:
        self._set_branch_archived(branch_id, archived=False)

    def _set_branch_archived(self, branch_id: int, *, archived: bool) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_branch(branch_id)
        now = self._clock()
        verb = "archive" if archived else "unarchive"
        self._mutate(
            action=f"directory.branch.{verb}",
            entity_type="branch",
            entity_id=branch_id,
            mutate=lambda: self._branches.set_archived(
                branch_id, archived=archived, updated_at=now
            ),
        )

    # --- Departments ---

    def list_departments(self, *, branch_id: int | None = None, active_only: bool = False):
        self._require(Permission.VIEW_DIRECTORIES)
        return self._departments.list(branch_id=branch_id, active_only=active_only)

    def create_department(self, branch_id: int, name: str) -> int:
        self._require(Permission.MANAGE_DIRECTORIES)
        branch = self._require_branch(branch_id)
        if branch.is_archived:
            raise DirectoryError("cannot assign to archived branch")
        clean = _clean_name(name)
        now = self._clock()
        return self._mutate(
            action="directory.department.create",
            entity_type="department",
            mutate=lambda: self._departments.create(
                branch_id=branch_id, name=clean, created_at=now
            ),
            details=f"branch_id={branch_id};name={clean}",
        )

    def rename_department(self, department_id: int, name: str) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_department(department_id)
        clean = _clean_name(name)
        now = self._clock()
        self._mutate(
            action="directory.department.rename",
            entity_type="department",
            entity_id=department_id,
            mutate=lambda: self._departments.rename(department_id, name=clean, updated_at=now),
            details=f"name={clean}",
        )

    def archive_department(self, department_id: int) -> None:
        self._set_department_archived(department_id, archived=True)

    def unarchive_department(self, department_id: int) -> None:
        self._set_department_archived(department_id, archived=False)

    def _set_department_archived(self, department_id: int, *, archived: bool) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_department(department_id)
        now = self._clock()
        verb = "archive" if archived else "unarchive"
        self._mutate(
            action=f"directory.department.{verb}",
            entity_type="department",
            entity_id=department_id,
            mutate=lambda: self._departments.set_archived(
                department_id, archived=archived, updated_at=now
            ),
        )

    # --- Divisions ---

    def list_divisions(self, *, department_id: int | None = None, active_only: bool = False):
        self._require(Permission.VIEW_DIRECTORIES)
        return self._divisions.list(department_id=department_id, active_only=active_only)

    def create_division(self, department_id: int, name: str) -> int:
        self._require(Permission.MANAGE_DIRECTORIES)
        department = self._require_department(department_id)
        if department.is_archived:
            raise DirectoryError("cannot assign to archived department")
        clean = _clean_name(name)
        now = self._clock()
        return self._mutate(
            action="directory.division.create",
            entity_type="division",
            mutate=lambda: self._divisions.create(
                department_id=department_id, name=clean, created_at=now
            ),
            details=f"department_id={department_id};name={clean}",
        )

    def rename_division(self, division_id: int, name: str) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_division(division_id)
        clean = _clean_name(name)
        now = self._clock()
        self._mutate(
            action="directory.division.rename",
            entity_type="division",
            entity_id=division_id,
            mutate=lambda: self._divisions.rename(division_id, name=clean, updated_at=now),
            details=f"name={clean}",
        )

    def archive_division(self, division_id: int) -> None:
        self._set_division_archived(division_id, archived=True)

    def unarchive_division(self, division_id: int) -> None:
        self._set_division_archived(division_id, archived=False)

    def _set_division_archived(self, division_id: int, *, archived: bool) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_division(division_id)
        now = self._clock()
        verb = "archive" if archived else "unarchive"
        self._mutate(
            action=f"directory.division.{verb}",
            entity_type="division",
            entity_id=division_id,
            mutate=lambda: self._divisions.set_archived(
                division_id, archived=archived, updated_at=now
            ),
        )

    # --- Positions ---

    def list_positions(self, *, active_only: bool = False):
        self._require(Permission.VIEW_DIRECTORIES)
        return self._positions.list(active_only=active_only)

    def create_position(self, name: str) -> int:
        self._require(Permission.MANAGE_DIRECTORIES)
        clean = _clean_name(name)
        now = self._clock()
        return self._mutate(
            action="directory.position.create",
            entity_type="position",
            mutate=lambda: self._positions.create(name=clean, created_at=now),
            details=f"name={clean}",
        )

    def rename_position(self, position_id: int, name: str) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_position(position_id)
        clean = _clean_name(name)
        now = self._clock()
        self._mutate(
            action="directory.position.rename",
            entity_type="position",
            entity_id=position_id,
            mutate=lambda: self._positions.rename(position_id, name=clean, updated_at=now),
            details=f"name={clean}",
        )

    def archive_position(self, position_id: int) -> None:
        self._set_position_archived(position_id, archived=True)

    def unarchive_position(self, position_id: int) -> None:
        self._set_position_archived(position_id, archived=False)

    def _set_position_archived(self, position_id: int, *, archived: bool) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_position(position_id)
        now = self._clock()
        verb = "archive" if archived else "unarchive"
        self._mutate(
            action=f"directory.position.{verb}",
            entity_type="position",
            entity_id=position_id,
            mutate=lambda: self._positions.set_archived(
                position_id, archived=archived, updated_at=now
            ),
        )

    # --- Employment types ---

    def list_employment_types(self, *, active_only: bool = False):
        self._require(Permission.VIEW_DIRECTORIES)
        return self._employment_types.list(active_only=active_only)

    def create_employment_type(self, code: str, name: str) -> int:
        self._require(Permission.MANAGE_DIRECTORIES)
        clean_code = _clean_code(code)
        clean_name = _clean_name(name)
        if self._employment_types.get_by_code(clean_code) is not None:
            raise DirectoryError("employment type code already exists")
        now = self._clock()
        return self._mutate(
            action="directory.employment_type.create",
            entity_type="employment_type",
            mutate=lambda: self._employment_types.create(
                code=clean_code, name=clean_name, created_at=now
            ),
            details=f"code={clean_code};name={clean_name}",
        )

    def rename_employment_type(self, employment_type_id: int, name: str) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_employment_type(employment_type_id)
        clean = _clean_name(name)
        now = self._clock()
        self._mutate(
            action="directory.employment_type.rename",
            entity_type="employment_type",
            entity_id=employment_type_id,
            mutate=lambda: self._employment_types.rename(
                employment_type_id, name=clean, updated_at=now
            ),
            details=f"name={clean}",
        )

    def archive_employment_type(self, employment_type_id: int) -> None:
        self._set_employment_type_archived(employment_type_id, archived=True)

    def unarchive_employment_type(self, employment_type_id: int) -> None:
        self._set_employment_type_archived(employment_type_id, archived=False)

    def _set_employment_type_archived(self, employment_type_id: int, *, archived: bool) -> None:
        self._require(Permission.MANAGE_DIRECTORIES)
        self._require_employment_type(employment_type_id)
        now = self._clock()
        verb = "archive" if archived else "unarchive"
        self._mutate(
            action=f"directory.employment_type.{verb}",
            entity_type="employment_type",
            entity_id=employment_type_id,
            mutate=lambda: self._employment_types.set_archived(
                employment_type_id, archived=archived, updated_at=now
            ),
        )

    # --- internals ---

    def _require(self, permission: Permission) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, permission)

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
                raise DirectoryError("mutation did not yield entity id")
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

    def _require_branch(self, branch_id: int):
        row = self._branches.get(branch_id)
        if row is None:
            raise DirectoryError("branch not found")
        return row

    def _require_department(self, department_id: int):
        row = self._departments.get(department_id)
        if row is None:
            raise DirectoryError("department not found")
        return row

    def _require_division(self, division_id: int):
        row = self._divisions.get(division_id)
        if row is None:
            raise DirectoryError("division not found")
        return row

    def _require_position(self, position_id: int):
        row = self._positions.get(position_id)
        if row is None:
            raise DirectoryError("position not found")
        return row

    def _require_employment_type(self, employment_type_id: int):
        row = self._employment_types.get(employment_type_id)
        if row is None:
            raise DirectoryError("employment type not found")
        return row


def _clean_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        raise DirectoryError("name must not be empty")
    return clean


def _clean_code(code: str) -> str:
    clean = code.strip().lower()
    if not clean:
        raise DirectoryError("code must not be empty")
    return clean


__all__ = ["AuthorizationError", "DirectoryError", "DirectoryService"]
