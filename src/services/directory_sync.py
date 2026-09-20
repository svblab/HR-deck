"""Compose incremental directory-sync export packages (ADR-0010 Part 3).

Self-contained export composition only — does not encrypt, sign, or send.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

from data.db import Connection
from data.directories import (
    BranchRepository,
    DepartmentRecord,
    DepartmentRepository,
    DivisionRecord,
    DivisionRepository,
    PositionRecord,
    PositionRepository,
)
from data.employees import EmployeeRecord, EmployeeRepository
from domain.directory_sync import SYNCED_TABLES, DirectorySyncPackage
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.installation_identity import InstallationIdentityService
from services.session import SessionState


class DirectorySyncService:
    """Build table-level incremental export packages and record watermarks."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._authz = authz or AuthorizationService()
        self._branches = BranchRepository(conn)
        self._departments = DepartmentRepository(conn)
        self._divisions = DivisionRepository(conn)
        self._positions = PositionRepository(conn)
        self._employees = EmployeeRepository(conn)

    def build_export_package(self, direction_id: int) -> DirectorySyncPackage:
        self._require_transport_admin()
        home_branch = InstallationIdentityService(
            self._conn, self._session
        ).require_home_branch()
        home_branch_id = home_branch.id
        watermarks = self._load_watermarks(direction_id)
        tables: dict[str, list[dict[str, object]]] = {}

        def scoped_branches(rows: Sequence[Any]) -> list[Any]:
            return [row for row in rows if row.id == home_branch_id]

        def scoped_by_branch(rows: Sequence[Any]) -> list[Any]:
            return [row for row in rows if row.branch_id == home_branch_id]

        def include_if_changed(table_name: str, rows: Sequence[Any]) -> None:
            watermark = watermarks.get(table_name, "")
            # Whole-table granularity: if any row changed since the watermark,
            # include *all* current rows for that table (not a row-level diff).
            if any(row.updated_at > watermark for row in rows):
                if table_name == "departments":
                    tables[table_name] = [self._department_export_row(row) for row in rows]
                elif table_name == "divisions":
                    tables[table_name] = [self._division_export_row(row) for row in rows]
                elif table_name == "positions":
                    tables[table_name] = [self._position_export_row(row) for row in rows]
                elif table_name == "employees":
                    tables[table_name] = [self._employee_export_row(row) for row in rows]
                else:
                    tables[table_name] = [dataclasses.asdict(row) for row in rows]

        # active_only=False deliberately: archived rows must be in every dump so
        # the receiving side (Part 4 reconciliation) sees complete current state,
        # not only the active subset.
        include_if_changed(
            "branches",
            scoped_branches(self._branches.list(active_only=False)),
        )
        include_if_changed(
            "departments",
            scoped_by_branch(self._departments.list(active_only=False)),
        )
        include_if_changed(
            "divisions",
            scoped_by_branch(self._divisions.list(active_only=False)),
        )
        include_if_changed(
            "positions",
            scoped_by_branch(self._positions.list(active_only=False)),
        )
        include_if_changed(
            "employees",
            scoped_by_branch(self._employees.list(active_only=False)),
        )
        assert set(tables).issubset(SYNCED_TABLES)
        return DirectorySyncPackage(tables=tables)

    def _department_export_row(self, row: DepartmentRecord) -> dict[str, object]:
        branch = self._branches.get(row.branch_id)
        assert branch is not None  # every department has a valid local branch
        return {
            # sender-local id; must never be used to resolve anything on the receiver
            "id": row.id,
            "external_id": row.external_id,
            "branch_external_id": branch.external_id,
            "name": row.name,
            "is_archived": row.is_archived,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _division_export_row(self, row: DivisionRecord) -> dict[str, object]:
        branch = self._branches.get(row.branch_id)
        assert branch is not None  # every division has a valid local branch
        department_external_id: str | None
        if row.department_id is None:
            department_external_id = None
        else:
            department = self._departments.get(row.department_id)
            assert department is not None
            department_external_id = department.external_id
        return {
            # sender-local id; must never be used to resolve anything on the receiver
            "id": row.id,
            "external_id": row.external_id,
            "branch_external_id": branch.external_id,
            "department_external_id": department_external_id,
            "name": row.name,
            "is_archived": row.is_archived,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _position_export_row(self, row: PositionRecord) -> dict[str, object]:
        branch = self._branches.get(row.branch_id)
        assert branch is not None  # every position has a valid local branch
        return {
            # sender-local id; must never be used to resolve anything on the receiver
            "id": row.id,
            "external_id": row.external_id,
            "branch_external_id": branch.external_id,
            "name": row.name,
            "department_required": row.department_required,
            "division_required": row.division_required,
            "is_archived": row.is_archived,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def _employee_export_row(self, row: EmployeeRecord) -> dict[str, object]:
        branch = self._branches.get(row.branch_id)
        assert branch is not None
        position = self._positions.get(row.position_id)
        assert position is not None
        department_external_id: str | None = None
        if row.department_id is not None:
            department = self._departments.get(row.department_id)
            assert department is not None
            department_external_id = department.external_id
        division_external_id: str | None = None
        if row.division_id is not None:
            division = self._divisions.get(row.division_id)
            assert division is not None
            division_external_id = division.external_id
        return {
            "id": row.id,
            "external_id": row.external_id,
            "full_name": row.full_name,
            "position_external_id": position.external_id,
            "branch_external_id": branch.external_id,
            "department_external_id": department_external_id,
            "division_external_id": division_external_id,
            # employment_type_id is intentionally left as a plain integer:
            # employment_types are fixed system seeds (staff/temporary/
            # contractor, ids 1-3 from migration 0001), identical across
            # every installation by design, not locally created — this is
            # a deliberate exception, not an oversight. ADR-0010 explicitly
            # excludes employment_types from the synced entity set.
            "employment_type_id": row.employment_type_id,
            "note": row.note,
            "hire_date": row.hire_date,
            "contacts": row.contacts,
            "home_address": row.home_address,
            "social_insurance_number": row.social_insurance_number,
            "needs_org_review": row.needs_org_review,
            "is_archived": row.is_archived,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def record_export(
        self,
        direction_id: int,
        table_names: list[str],
        *,
        exported_at: str,
    ) -> None:
        """Bump watermarks only for tables that were actually exported."""
        self._require_transport_admin()
        allowed = set(SYNCED_TABLES)
        try:
            for table_name in table_names:
                if table_name not in allowed:
                    raise ValueError(f"unknown sync table: {table_name}")
                self._conn.execute(
                    "INSERT INTO sync_watermarks (direction_id, table_name, last_exported_at)"
                    " VALUES (?, ?, ?)"
                    " ON CONFLICT(direction_id, table_name) DO UPDATE SET"
                    " last_exported_at = excluded.last_exported_at",
                    (direction_id, table_name, exported_at),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _load_watermarks(self, direction_id: int) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT table_name, last_exported_at FROM sync_watermarks WHERE direction_id = ?",
            (direction_id,),
        ).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    def _require_transport_admin(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.MANAGE_ENCRYPTION_KEYS)
