"""Репозиторий справочника статусов доступности (EPIC-006)."""

from __future__ import annotations

from dataclasses import dataclass

from data.db import Connection


@dataclass(frozen=True)
class AvailabilityStatusRecord:
    id: int
    code: str
    name: str
    end_date_policy: int
    color_hex: str | None
    sort_order: int
    is_archived: bool
    created_at: str
    updated_at: str


class AvailabilityStatusRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(self, *, active_only: bool = False) -> list[AvailabilityStatusRecord]:
        sql = (
            "SELECT id, code, name, end_date_policy, color_hex, sort_order,"
            " is_archived, created_at, updated_at"
            " FROM availability_statuses"
        )
        if active_only:
            sql += " WHERE is_archived = 0"
        sql += " ORDER BY sort_order, name"
        return [_row(r) for r in self._conn.execute(sql).fetchall()]

    def get(self, status_id: int) -> AvailabilityStatusRecord | None:
        row = self._conn.execute(
            "SELECT id, code, name, end_date_policy, color_hex, sort_order,"
            " is_archived, created_at, updated_at"
            " FROM availability_statuses WHERE id = ?",
            (status_id,),
        ).fetchone()
        return _row(row) if row else None

    def get_by_code(self, code: str) -> AvailabilityStatusRecord | None:
        row = self._conn.execute(
            "SELECT id, code, name, end_date_policy, color_hex, sort_order,"
            " is_archived, created_at, updated_at"
            " FROM availability_statuses WHERE code = ?",
            (code,),
        ).fetchone()
        return _row(row) if row else None

    def create(
        self,
        *,
        code: str,
        name: str,
        end_date_policy: int,
        color_hex: str | None,
        sort_order: int,
        created_at: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO availability_statuses ("
            " code, name, end_date_policy, color_hex, sort_order,"
            " is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (code, name, end_date_policy, color_hex, sort_order, created_at, created_at),
        )
        return int(cur.lastrowid)

    def rename(self, status_id: int, *, name: str, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE availability_statuses SET name = ?, updated_at = ? WHERE id = ?",
            (name, updated_at, status_id),
        )

    def update_display(
        self,
        status_id: int,
        *,
        color_hex: str | None,
        sort_order: int,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            "UPDATE availability_statuses SET color_hex = ?, sort_order = ?, updated_at = ?"
            " WHERE id = ?",
            (color_hex, sort_order, updated_at, status_id),
        )

    def set_archived(self, status_id: int, *, archived: bool, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE availability_statuses SET is_archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, updated_at, status_id),
        )


def _row(row: tuple[object, ...]) -> AvailabilityStatusRecord:
    return AvailabilityStatusRecord(
        id=int(row[0]),
        code=str(row[1]),
        name=str(row[2]),
        end_date_policy=int(row[3]),
        color_hex=str(row[4]) if row[4] is not None else None,
        sort_order=int(row[5]),
        is_archived=bool(int(row[6])),
        created_at=str(row[7]),
        updated_at=str(row[8]),
    )
