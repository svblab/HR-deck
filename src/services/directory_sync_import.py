"""Apply a directory sync package (ADR-0010 Part 4a).

Reconciles branches/departments/divisions/positions by external_id inside a
SAVEPOINT, verifies no active employee is broken, then commits or rejects the
whole package. Employee-row reconciliation is Part 4b (out of scope here).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from data.db import Connection
from data.directories import (
    BranchRepository,
    DepartmentRepository,
    DivisionRepository,
    PositionRepository,
)
from domain.directory_sync import DirectorySyncConflictError, DirectorySyncPackage
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]

_SAVEPOINT = "directory_sync_apply"

_BROKEN_EMPLOYEES_SQL = """
SELECT e.id, e.full_name FROM employees e
WHERE e.is_archived = 0
AND (
    (e.department_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM departments d
        WHERE d.id = e.department_id AND d.branch_id = e.branch_id
    ))
    OR (e.division_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM divisions v
        WHERE v.id = e.division_id AND v.branch_id = e.branch_id
        AND (
            (v.department_id IS NULL AND e.department_id IS NULL)
            OR v.department_id = e.department_id
        )
    ))
    OR NOT EXISTS (
        SELECT 1 FROM positions p
        WHERE p.id = e.position_id AND p.branch_id = e.branch_id
    )
    OR (EXISTS (
        SELECT 1 FROM positions p
        WHERE p.id = e.position_id AND p.department_required = 1
    ) AND e.department_id IS NULL)
    OR (EXISTS (
        SELECT 1 FROM positions p
        WHERE p.id = e.position_id AND p.division_required = 1
    ) AND e.division_id IS NULL)
)
"""


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

    def apply_package(self, package: DirectorySyncPackage) -> None:
        self._require_transport_admin()
        self._conn.execute(f"SAVEPOINT {_SAVEPOINT}")
        try:
            branch_map = self._reconcile_branches(package.tables.get("branches", []))
            dept_map = self._reconcile_departments(
                package.tables.get("departments", []),
                branch_map,
                package.tables.get("branches", []),
            )
            self._reconcile_divisions(
                package.tables.get("divisions", []),
                branch_map,
                dept_map,
                package.tables.get("branches", []),
                package.tables.get("departments", []),
            )
            self._reconcile_positions(
                package.tables.get("positions", []),
                branch_map,
                package.tables.get("branches", []),
            )

            broken = self._find_broken_active_employees()
            if broken:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
                self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                raise DirectorySyncConflictError(broken)

            self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            self._conn.commit()
        except DirectorySyncConflictError:
            raise
        except Exception:
            self._conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
            self._conn.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            raise

    def _require_transport_admin(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.MANAGE_ENCRYPTION_KEYS)

    def _find_broken_active_employees(self) -> list[tuple[int, str]]:
        rows = self._conn.execute(_BROKEN_EMPLOYEES_SQL).fetchall()
        return [(int(r[0]), str(r[1])) for r in rows]

    def _reconcile_branches(
        self, rows: list[dict[str, object]]
    ) -> dict[int, int]:
        now = self._clock()
        id_map: dict[int, int] = {}
        for row in rows:
            package_id = int(row["id"])
            external_id = str(row["external_id"])
            name = str(row["name"])
            is_archived = bool(row["is_archived"])
            local = self._branches.get_by_external_id(external_id)
            if local is None:
                local_id = self._branches.create(
                    external_id=external_id, name=name, created_at=now
                )
                if is_archived:
                    self._branches.set_archived(
                        local_id, archived=True, updated_at=now
                    )
            else:
                local_id = local.id
                if local.name != name:
                    self._branches.rename(local_id, name=name, updated_at=now)
                if local.is_archived != is_archived:
                    self._branches.set_archived(
                        local_id, archived=is_archived, updated_at=now
                    )
            id_map[package_id] = local_id
        return id_map

    def _reconcile_departments(
        self,
        rows: list[dict[str, object]],
        branch_map: dict[int, int],
        package_branches: list[dict[str, object]],
    ) -> dict[int, int]:
        now = self._clock()
        id_map: dict[int, int] = {}
        for row in rows:
            package_id = int(row["id"])
            external_id = str(row["external_id"])
            name = str(row["name"])
            is_archived = bool(row["is_archived"])
            local_branch_id = self._resolve_fk(
                int(row["branch_id"]),
                branch_map,
                package_branches,
                self._branches.get_by_external_id,
                self._branches.get,
                "branch",
            )
            local = self._departments.get_by_external_id(external_id)
            if local is None:
                local_id = self._departments.create(
                    external_id=external_id,
                    branch_id=local_branch_id,
                    name=name,
                    created_at=now,
                )
                if is_archived:
                    self._departments.set_archived(
                        local_id, archived=True, updated_at=now
                    )
            else:
                local_id = local.id
                if local.name != name:
                    self._departments.rename(local_id, name=name, updated_at=now)
                if local.branch_id != local_branch_id:
                    self._departments.set_branch(
                        local_id, branch_id=local_branch_id, updated_at=now
                    )
                if local.is_archived != is_archived:
                    self._departments.set_archived(
                        local_id, archived=is_archived, updated_at=now
                    )
            id_map[package_id] = local_id
        return id_map

    def _reconcile_divisions(
        self,
        rows: list[dict[str, object]],
        branch_map: dict[int, int],
        dept_map: dict[int, int],
        package_branches: list[dict[str, object]],
        package_departments: list[dict[str, object]],
    ) -> dict[int, int]:
        now = self._clock()
        id_map: dict[int, int] = {}
        for row in rows:
            package_id = int(row["id"])
            external_id = str(row["external_id"])
            name = str(row["name"])
            is_archived = bool(row["is_archived"])
            local_branch_id = self._resolve_fk(
                int(row["branch_id"]),
                branch_map,
                package_branches,
                self._branches.get_by_external_id,
                self._branches.get,
                "branch",
            )
            pkg_dept = row["department_id"]
            local_dept_id: int | None
            if pkg_dept is None:
                local_dept_id = None
            else:
                local_dept_id = self._resolve_fk(
                    int(pkg_dept),
                    dept_map,
                    package_departments,
                    self._departments.get_by_external_id,
                    self._departments.get,
                    "department",
                )
            local = self._divisions.get_by_external_id(external_id)
            if local is None:
                local_id = self._divisions.create(
                    external_id=external_id,
                    branch_id=local_branch_id,
                    department_id=local_dept_id,
                    name=name,
                    created_at=now,
                )
                if is_archived:
                    self._divisions.set_archived(
                        local_id, archived=True, updated_at=now
                    )
            else:
                local_id = local.id
                if local.name != name:
                    self._divisions.rename(local_id, name=name, updated_at=now)
                if (
                    local.branch_id != local_branch_id
                    or local.department_id != local_dept_id
                ):
                    self._divisions.set_parentage(
                        local_id,
                        branch_id=local_branch_id,
                        department_id=local_dept_id,
                        updated_at=now,
                    )
                if local.is_archived != is_archived:
                    self._divisions.set_archived(
                        local_id, archived=is_archived, updated_at=now
                    )
            id_map[package_id] = local_id
        return id_map

    def _reconcile_positions(
        self,
        rows: list[dict[str, object]],
        branch_map: dict[int, int],
        package_branches: list[dict[str, object]],
    ) -> dict[int, int]:
        now = self._clock()
        id_map: dict[int, int] = {}
        for row in rows:
            package_id = int(row["id"])
            external_id = str(row["external_id"])
            name = str(row["name"])
            is_archived = bool(row["is_archived"])
            dept_req = bool(row["department_required"])
            div_req = bool(row["division_required"])
            local_branch_id = self._resolve_fk(
                int(row["branch_id"]),
                branch_map,
                package_branches,
                self._branches.get_by_external_id,
                self._branches.get,
                "branch",
            )
            local = self._positions.get_by_external_id(external_id)
            if local is None:
                local_id = self._positions.create(
                    external_id=external_id,
                    branch_id=local_branch_id,
                    name=name,
                    department_required=dept_req,
                    division_required=div_req,
                    created_at=now,
                )
                if is_archived:
                    self._positions.set_archived(
                        local_id, archived=True, updated_at=now
                    )
            else:
                local_id = local.id
                if local.name != name:
                    self._positions.rename(local_id, name=name, updated_at=now)
                if local.branch_id != local_branch_id:
                    self._positions.set_branch(
                        local_id, branch_id=local_branch_id, updated_at=now
                    )
                if (
                    local.department_required != dept_req
                    or local.division_required != div_req
                ):
                    self._positions.set_org_requirements(
                        local_id,
                        department_required=dept_req,
                        division_required=div_req,
                        updated_at=now,
                    )
                if local.is_archived != is_archived:
                    self._positions.set_archived(
                        local_id, archived=is_archived, updated_at=now
                    )
            id_map[package_id] = local_id
        return id_map

    def _resolve_fk(
        self,
        package_fk: int,
        id_map: dict[int, int],
        package_parent_rows: list[dict[str, object]],
        get_by_external_id: Callable[[str], Any],
        get_by_id: Callable[[int], Any],
        label: str,
    ) -> int:
        if package_fk in id_map:
            return id_map[package_fk]
        for parent in package_parent_rows:
            if int(parent["id"]) == package_fk:
                record = get_by_external_id(str(parent["external_id"]))
                if record is None:
                    raise ValueError(
                        f"cannot resolve {label} package id {package_fk}: "
                        "external_id not present locally"
                    )
                return int(record.id)
        record = get_by_id(package_fk)
        if record is not None:
            return int(record.id)
        raise ValueError(f"cannot resolve {label} package id {package_fk}")
