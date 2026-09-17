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
    DepartmentRepository,
    DivisionRepository,
    PositionRepository,
)
from data.employees import EmployeeRepository
from domain.directory_sync import SYNCED_TABLES, DirectorySyncPackage
from domain.permissions import Permission
from services.authorization import AuthorizationService
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
        watermarks = self._load_watermarks(direction_id)
        tables: dict[str, list[dict[str, object]]] = {}

        def include_if_changed(table_name: str, rows: Sequence[Any]) -> None:
            watermark = watermarks.get(table_name, "")
            # Whole-table granularity: if any row changed since the watermark,
            # include *all* current rows for that table (not a row-level diff).
            if any(row.updated_at > watermark for row in rows):
                tables[table_name] = [dataclasses.asdict(row) for row in rows]

        # active_only=False deliberately: archived rows must be in every dump so
        # the receiving side (Part 4 reconciliation) sees complete current state,
        # not only the active subset.
        include_if_changed("branches", self._branches.list(active_only=False))
        include_if_changed("departments", self._departments.list(active_only=False))
        include_if_changed("divisions", self._divisions.list(active_only=False))
        include_if_changed("positions", self._positions.list(active_only=False))
        include_if_changed("employees", self._employees.list(active_only=False))
        assert set(tables).issubset(SYNCED_TABLES)
        return DirectorySyncPackage(tables=tables)

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
            "SELECT table_name, last_exported_at FROM sync_watermarks"
            " WHERE direction_id = ?",
            (direction_id,),
        ).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    def _require_transport_admin(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.MANAGE_ENCRYPTION_KEYS)
