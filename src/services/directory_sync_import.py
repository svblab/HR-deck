"""Apply a directory sync package (ADR-0010 Part 4a).

Plan/apply split (ADR-0010 addendum): ``build_directory_plan`` is pure
(no writes); ``apply_directory_plan`` performs writes. ``apply_package``
builds both directory and employee plans, then applies them atomically.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from data.db import Connection
from data.directories import (
    BranchRecord,
    BranchRepository,
    DepartmentRecord,
    DepartmentRepository,
    DivisionRecord,
    DivisionRepository,
    PositionRecord,
    PositionRepository,
)
from domain.directory_sync import DirectorySyncConflictError, DirectorySyncPackage
from domain.employee_reconciliation import EmployeeSyncApplyError, EmployeeSyncConflictError
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]

_SAVEPOINT = "directory_sync_apply"


@dataclass(frozen=True)
class _BranchCreate:
    external_id: str
    name: str
    is_archived: bool


@dataclass(frozen=True)
class _BranchUpdate:
    local_id: int
    name: str | None
    is_archived: bool | None


@dataclass(frozen=True)
class _DepartmentCreate:
    external_id: str
    branch_external_id: str
    name: str
    is_archived: bool


@dataclass(frozen=True)
class _DepartmentUpdate:
    local_id: int
    branch_external_id: str
    name: str | None
    branch_changed: bool
    is_archived: bool | None


@dataclass(frozen=True)
class _DivisionCreate:
    external_id: str
    branch_external_id: str
    department_external_id: str | None
    name: str
    is_archived: bool


@dataclass(frozen=True)
class _DivisionUpdate:
    local_id: int
    branch_external_id: str
    department_external_id: str | None
    name: str | None
    parentage_changed: bool
    is_archived: bool | None


@dataclass(frozen=True)
class _PositionCreate:
    external_id: str
    branch_external_id: str
    name: str
    department_required: bool
    division_required: bool
    is_archived: bool


@dataclass(frozen=True)
class _PositionUpdate:
    local_id: int
    branch_external_id: str
    name: str | None
    branch_changed: bool
    department_required: bool | None
    division_required: bool | None
    is_archived: bool | None


@dataclass
class DirectoryPlan:
    """Pure directory apply plan (no DB writes performed to produce it)."""

    branch_creates: list[_BranchCreate] = field(default_factory=list)
    branch_updates: list[_BranchUpdate] = field(default_factory=list)
    department_creates: list[_DepartmentCreate] = field(default_factory=list)
    department_updates: list[_DepartmentUpdate] = field(default_factory=list)
    division_creates: list[_DivisionCreate] = field(default_factory=list)
    division_updates: list[_DivisionUpdate] = field(default_factory=list)
    position_creates: list[_PositionCreate] = field(default_factory=list)
    position_updates: list[_PositionUpdate] = field(default_factory=list)
    broken_employees: list[tuple[int, str]] = field(default_factory=list)
    # Projected external_id → local-or-provisional id (provisional ids are < 0).
    branch_ids: dict[str, int] = field(default_factory=dict)
    department_ids: dict[str, int] = field(default_factory=dict)
    division_ids: dict[str, int] = field(default_factory=dict)
    position_ids: dict[str, int] = field(default_factory=dict)
    projected_branches: dict[int, BranchRecord] = field(default_factory=dict)
    projected_departments: dict[int, DepartmentRecord] = field(default_factory=dict)
    projected_divisions: dict[int, DivisionRecord] = field(default_factory=dict)
    projected_positions: dict[int, PositionRecord] = field(default_factory=dict)

    @property
    def is_clean(self) -> bool:
        return not self.broken_employees


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DirectorySyncImportService:
    """Apply directory tables from a sync package (parents before children)."""

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
        self._branches = BranchRepository(conn)
        self._departments = DepartmentRepository(conn)
        self._divisions = DivisionRepository(conn)
        self._positions = PositionRepository(conn)

    def build_directory_plan(self, package: DirectorySyncPackage) -> DirectoryPlan:
        """Pure: SELECTs only. No SAVEPOINT, no writes."""
        self._require_transport_admin()
        plan = DirectoryPlan()
        self._seed_projected_from_db(plan)
        next_prov = -1

        for row in package.tables.get("branches", []):
            next_prov = self._plan_branch(plan, row, next_prov)
        for row in package.tables.get("departments", []):
            next_prov = self._plan_department(plan, row, next_prov)
        for row in package.tables.get("divisions", []):
            next_prov = self._plan_division(plan, row, next_prov)
        for row in package.tables.get("positions", []):
            next_prov = self._plan_position(plan, row, next_prov)

        plan.broken_employees = self._find_broken_against_projected(plan)
        return plan

    def apply_directory_plan(self, plan: DirectoryPlan, *, commit: bool = True) -> None:
        """Write directory ops from an already-built plan."""
        self._require_transport_admin()
        if not plan.is_clean:
            raise DirectorySyncConflictError(list(plan.broken_employees))
        if commit:
            self._conn.execute(f"SAVEPOINT {_SAVEPOINT}")
            try:
                self._write_directory_plan(plan)
                self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                self._conn.commit()
            except Exception:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
                self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                raise
        else:
            self._write_directory_plan(plan)

    def apply_package(self, package: DirectorySyncPackage) -> None:
        """File-based Part 4a/4b entry: build plans, then apply atomically."""
        self._require_transport_admin()
        dir_plan = self.build_directory_plan(package)
        if not dir_plan.is_clean:
            raise DirectorySyncConflictError(list(dir_plan.broken_employees))

        from services.employee_sync_import import EmployeeSyncImportService

        emp_svc = EmployeeSyncImportService(
            self._conn,
            self._session,
            clock=self._clock,
            authz=self._authz,
        )
        emp_plan = emp_svc.build_employee_plan(package, dir_plan)
        if emp_plan.conflicts:
            raise EmployeeSyncConflictError(list(emp_plan.conflicts))
        if emp_plan.validation_errors:
            raise EmployeeSyncApplyError("; ".join(emp_plan.validation_errors))

        self._conn.execute(f"SAVEPOINT {_SAVEPOINT}")
        try:
            self.apply_directory_plan(dir_plan, commit=False)
            emp_svc.apply_employee_plan(emp_plan, commit=False)
            self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            self._conn.commit()
        except DirectorySyncConflictError:
            raise
        except (EmployeeSyncConflictError, EmployeeSyncApplyError):
            self._conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
            self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            raise
        except Exception:
            self._conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
            self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            raise

    def _require_transport_admin(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.MANAGE_ENCRYPTION_KEYS)

    def _seed_projected_from_db(self, plan: DirectoryPlan) -> None:
        for b in self._branches.list(active_only=False):
            plan.branch_ids[b.external_id] = b.id
            plan.projected_branches[b.id] = b
        for d in self._departments.list(active_only=False):
            plan.department_ids[d.external_id] = d.id
            plan.projected_departments[d.id] = d
        for v in self._divisions.list(active_only=False):
            plan.division_ids[v.external_id] = v.id
            plan.projected_divisions[v.id] = v
        for p in self._positions.list(active_only=False):
            plan.position_ids[p.external_id] = p.id
            plan.projected_positions[p.id] = p

    def _plan_branch(self, plan: DirectoryPlan, row: dict[str, object], next_prov: int) -> int:
        external_id = str(row["external_id"])
        name = str(row["name"])
        is_archived = bool(row["is_archived"])
        local_id = plan.branch_ids.get(external_id)
        if local_id is None:
            plan.branch_creates.append(
                _BranchCreate(external_id=external_id, name=name, is_archived=is_archived)
            )
            prov = next_prov
            next_prov -= 1
            plan.branch_ids[external_id] = prov
            plan.projected_branches[prov] = BranchRecord(
                id=prov,
                external_id=external_id,
                name=name,
                is_archived=is_archived,
                created_at="",
                updated_at="",
            )
            return next_prov
        cur = plan.projected_branches[local_id]
        name_chg = name if cur.name != name else None
        arch_chg = is_archived if cur.is_archived != is_archived else None
        if name_chg is not None or arch_chg is not None:
            plan.branch_updates.append(
                _BranchUpdate(local_id=local_id, name=name_chg, is_archived=arch_chg)
            )
            plan.projected_branches[local_id] = BranchRecord(
                id=cur.id,
                external_id=cur.external_id,
                name=name if name_chg is not None else cur.name,
                is_archived=is_archived if arch_chg is not None else cur.is_archived,
                created_at=cur.created_at,
                updated_at=cur.updated_at,
            )
        return next_prov

    def _plan_department(
        self, plan: DirectoryPlan, row: dict[str, object], next_prov: int
    ) -> int:
        external_id = str(row["external_id"])
        name = str(row["name"])
        is_archived = bool(row["is_archived"])
        branch_ext = str(row["branch_external_id"])
        if branch_ext not in plan.branch_ids:
            raise ValueError(
                f"cannot resolve branch external_id {branch_ext}: "
                "not present locally (package is missing a required "
                "branch, or was applied out of order)"
            )
        branch_id = plan.branch_ids[branch_ext]
        local_id = plan.department_ids.get(external_id)
        if local_id is None:
            plan.department_creates.append(
                _DepartmentCreate(
                    external_id=external_id,
                    branch_external_id=branch_ext,
                    name=name,
                    is_archived=is_archived,
                )
            )
            prov = next_prov
            next_prov -= 1
            plan.department_ids[external_id] = prov
            plan.projected_departments[prov] = DepartmentRecord(
                id=prov,
                external_id=external_id,
                branch_id=branch_id,
                name=name,
                is_archived=is_archived,
                created_at="",
                updated_at="",
            )
            return next_prov
        cur = plan.projected_departments[local_id]
        name_chg = name if cur.name != name else None
        branch_changed = cur.branch_id != branch_id
        arch_chg = is_archived if cur.is_archived != is_archived else None
        if name_chg is not None or branch_changed or arch_chg is not None:
            plan.department_updates.append(
                _DepartmentUpdate(
                    local_id=local_id,
                    branch_external_id=branch_ext,
                    name=name_chg,
                    branch_changed=branch_changed,
                    is_archived=arch_chg,
                )
            )
            plan.projected_departments[local_id] = DepartmentRecord(
                id=cur.id,
                external_id=cur.external_id,
                branch_id=branch_id,
                name=name if name_chg is not None else cur.name,
                is_archived=is_archived if arch_chg is not None else cur.is_archived,
                created_at=cur.created_at,
                updated_at=cur.updated_at,
            )
        return next_prov

    def _plan_division(
        self, plan: DirectoryPlan, row: dict[str, object], next_prov: int
    ) -> int:
        external_id = str(row["external_id"])
        name = str(row["name"])
        is_archived = bool(row["is_archived"])
        branch_ext = str(row["branch_external_id"])
        if branch_ext not in plan.branch_ids:
            raise ValueError(
                f"cannot resolve branch external_id {branch_ext}: "
                "not present locally (package is missing a required "
                "branch, or was applied out of order)"
            )
        branch_id = plan.branch_ids[branch_ext]
        pkg_dept = row["department_external_id"]
        dept_ext = None if pkg_dept is None else str(pkg_dept)
        if dept_ext is not None and dept_ext not in plan.department_ids:
            raise ValueError(
                f"cannot resolve department external_id {dept_ext}: "
                "not present locally (package is missing a required "
                "department, or was applied out of order)"
            )
        dept_id = None if dept_ext is None else plan.department_ids[dept_ext]
        local_id = plan.division_ids.get(external_id)
        if local_id is None:
            plan.division_creates.append(
                _DivisionCreate(
                    external_id=external_id,
                    branch_external_id=branch_ext,
                    department_external_id=dept_ext,
                    name=name,
                    is_archived=is_archived,
                )
            )
            prov = next_prov
            next_prov -= 1
            plan.division_ids[external_id] = prov
            plan.projected_divisions[prov] = DivisionRecord(
                id=prov,
                external_id=external_id,
                branch_id=branch_id,
                department_id=dept_id,
                name=name,
                is_archived=is_archived,
                created_at="",
                updated_at="",
            )
            return next_prov
        cur = plan.projected_divisions[local_id]
        name_chg = name if cur.name != name else None
        parentage_changed = cur.branch_id != branch_id or cur.department_id != dept_id
        arch_chg = is_archived if cur.is_archived != is_archived else None
        if name_chg is not None or parentage_changed or arch_chg is not None:
            plan.division_updates.append(
                _DivisionUpdate(
                    local_id=local_id,
                    branch_external_id=branch_ext,
                    department_external_id=dept_ext,
                    name=name_chg,
                    parentage_changed=parentage_changed,
                    is_archived=arch_chg,
                )
            )
            plan.projected_divisions[local_id] = DivisionRecord(
                id=cur.id,
                external_id=cur.external_id,
                branch_id=branch_id,
                department_id=dept_id,
                name=name if name_chg is not None else cur.name,
                is_archived=is_archived if arch_chg is not None else cur.is_archived,
                created_at=cur.created_at,
                updated_at=cur.updated_at,
            )
        return next_prov

    def _plan_position(
        self, plan: DirectoryPlan, row: dict[str, object], next_prov: int
    ) -> int:
        external_id = str(row["external_id"])
        name = str(row["name"])
        is_archived = bool(row["is_archived"])
        dept_req = bool(row["department_required"])
        div_req = bool(row["division_required"])
        branch_ext = str(row["branch_external_id"])
        if branch_ext not in plan.branch_ids:
            raise ValueError(
                f"cannot resolve branch external_id {branch_ext}: "
                "not present locally (package is missing a required "
                "branch, or was applied out of order)"
            )
        branch_id = plan.branch_ids[branch_ext]
        local_id = plan.position_ids.get(external_id)
        if local_id is None:
            plan.position_creates.append(
                _PositionCreate(
                    external_id=external_id,
                    branch_external_id=branch_ext,
                    name=name,
                    department_required=dept_req,
                    division_required=div_req,
                    is_archived=is_archived,
                )
            )
            prov = next_prov
            next_prov -= 1
            plan.position_ids[external_id] = prov
            plan.projected_positions[prov] = PositionRecord(
                id=prov,
                external_id=external_id,
                branch_id=branch_id,
                name=name,
                department_required=dept_req,
                division_required=div_req,
                is_archived=is_archived,
                created_at="",
                updated_at="",
            )
            return next_prov
        cur = plan.projected_positions[local_id]
        name_chg = name if cur.name != name else None
        branch_changed = cur.branch_id != branch_id
        req_chg = cur.department_required != dept_req or cur.division_required != div_req
        arch_chg = is_archived if cur.is_archived != is_archived else None
        if name_chg is not None or branch_changed or req_chg or arch_chg is not None:
            plan.position_updates.append(
                _PositionUpdate(
                    local_id=local_id,
                    branch_external_id=branch_ext,
                    name=name_chg,
                    branch_changed=branch_changed,
                    department_required=dept_req if req_chg else None,
                    division_required=div_req if req_chg else None,
                    is_archived=arch_chg,
                )
            )
            plan.projected_positions[local_id] = PositionRecord(
                id=cur.id,
                external_id=cur.external_id,
                branch_id=branch_id,
                name=name if name_chg is not None else cur.name,
                department_required=dept_req if req_chg else cur.department_required,
                division_required=div_req if req_chg else cur.division_required,
                is_archived=is_archived if arch_chg is not None else cur.is_archived,
                created_at=cur.created_at,
                updated_at=cur.updated_at,
            )
        return next_prov

    def _find_broken_against_projected(
        self, plan: DirectoryPlan
    ) -> list[tuple[int, str]]:
        """Mirror _BROKEN_EMPLOYEES_SQL against projected directory maps."""
        rows = self._conn.execute(
            "SELECT id, full_name, branch_id, department_id, division_id, position_id "
            "FROM employees WHERE is_archived = 0"
        ).fetchall()
        broken: list[tuple[int, str]] = []
        for r in rows:
            emp_id = int(r[0])
            full_name = str(r[1])
            branch_id = int(r[2])
            department_id = None if r[3] is None else int(r[3])
            division_id = None if r[4] is None else int(r[4])
            position_id = int(r[5])
            if department_id is not None:
                dept = plan.projected_departments.get(department_id)
                if dept is None or dept.branch_id != branch_id:
                    broken.append((emp_id, full_name))
                    continue
            if division_id is not None:
                div = plan.projected_divisions.get(division_id)
                if (
                    div is None
                    or div.branch_id != branch_id
                    or div.department_id != department_id
                ):
                    broken.append((emp_id, full_name))
                    continue
            pos = plan.projected_positions.get(position_id)
            if pos is None or pos.branch_id != branch_id:
                broken.append((emp_id, full_name))
                continue
            if pos.department_required and department_id is None:
                broken.append((emp_id, full_name))
                continue
            if pos.division_required and division_id is None:
                broken.append((emp_id, full_name))
                continue
        return broken

    def _write_directory_plan(self, plan: DirectoryPlan) -> None:
        now = self._clock()
        for b_create in plan.branch_creates:
            local_id = self._branches.create(
                external_id=b_create.external_id, name=b_create.name, created_at=now
            )
            if b_create.is_archived:
                self._branches.set_archived(local_id, archived=True, updated_at=now)
        for b_upd in plan.branch_updates:
            if b_upd.name is not None:
                self._branches.rename(b_upd.local_id, name=b_upd.name, updated_at=now)
            if b_upd.is_archived is not None:
                self._branches.set_archived(
                    b_upd.local_id, archived=b_upd.is_archived, updated_at=now
                )
        for d_create in plan.department_creates:
            branch_id = self._require_branch_id(d_create.branch_external_id)
            local_id = self._departments.create(
                external_id=d_create.external_id,
                branch_id=branch_id,
                name=d_create.name,
                created_at=now,
            )
            if d_create.is_archived:
                self._departments.set_archived(local_id, archived=True, updated_at=now)
        for d_upd in plan.department_updates:
            if d_upd.name is not None:
                self._departments.rename(d_upd.local_id, name=d_upd.name, updated_at=now)
            if d_upd.branch_changed:
                branch_id = self._require_branch_id(d_upd.branch_external_id)
                self._departments.set_branch(
                    d_upd.local_id, branch_id=branch_id, updated_at=now
                )
            if d_upd.is_archived is not None:
                self._departments.set_archived(
                    d_upd.local_id, archived=d_upd.is_archived, updated_at=now
                )
        for v_create in plan.division_creates:
            branch_id = self._require_branch_id(v_create.branch_external_id)
            dept_id = self._require_department_id(v_create.department_external_id)
            local_id = self._divisions.create(
                external_id=v_create.external_id,
                branch_id=branch_id,
                department_id=dept_id,
                name=v_create.name,
                created_at=now,
            )
            if v_create.is_archived:
                self._divisions.set_archived(local_id, archived=True, updated_at=now)
        for v_upd in plan.division_updates:
            if v_upd.name is not None:
                self._divisions.rename(v_upd.local_id, name=v_upd.name, updated_at=now)
            if v_upd.parentage_changed:
                branch_id = self._require_branch_id(v_upd.branch_external_id)
                dept_id = self._require_department_id(v_upd.department_external_id)
                self._divisions.set_parentage(
                    v_upd.local_id,
                    branch_id=branch_id,
                    department_id=dept_id,
                    updated_at=now,
                )
            if v_upd.is_archived is not None:
                self._divisions.set_archived(
                    v_upd.local_id, archived=v_upd.is_archived, updated_at=now
                )
        for p_create in plan.position_creates:
            branch_id = self._require_branch_id(p_create.branch_external_id)
            local_id = self._positions.create(
                external_id=p_create.external_id,
                branch_id=branch_id,
                name=p_create.name,
                department_required=p_create.department_required,
                division_required=p_create.division_required,
                created_at=now,
            )
            if p_create.is_archived:
                self._positions.set_archived(local_id, archived=True, updated_at=now)
        for p_upd in plan.position_updates:
            if p_upd.name is not None:
                self._positions.rename(p_upd.local_id, name=p_upd.name, updated_at=now)
            if p_upd.branch_changed:
                branch_id = self._require_branch_id(p_upd.branch_external_id)
                self._positions.set_branch(
                    p_upd.local_id, branch_id=branch_id, updated_at=now
                )
            if p_upd.department_required is not None and p_upd.division_required is not None:
                self._positions.set_org_requirements(
                    p_upd.local_id,
                    department_required=p_upd.department_required,
                    division_required=p_upd.division_required,
                    updated_at=now,
                )
            if p_upd.is_archived is not None:
                self._positions.set_archived(
                    p_upd.local_id, archived=p_upd.is_archived, updated_at=now
                )

    def _require_branch_id(self, external_id: str) -> int:
        record = self._branches.get_by_external_id(external_id)
        if record is None:
            raise ValueError(
                f"cannot resolve branch external_id {external_id}: "
                "not present locally (package is missing a required "
                "branch, or was applied out of order)"
            )
        return record.id

    def _require_department_id(self, external_id: str | None) -> int | None:
        if external_id is None:
            return None
        record = self._departments.get_by_external_id(external_id)
        if record is None:
            raise ValueError(
                f"cannot resolve department external_id {external_id}: "
                "not present locally (package is missing a required "
                "department, or was applied out of order)"
            )
        return record.id


__all__ = ["DirectoryPlan", "DirectorySyncImportService"]
