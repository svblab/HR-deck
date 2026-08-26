"""Репозитории истории статусов и append-only корректировок (EPIC-006)."""

from __future__ import annotations

from dataclasses import dataclass

from data.db import Connection
from data.repositories import AppendOnlyViolation, _AppendOnlyGuard


@dataclass(frozen=True)
class StatusHistoryRecord:
    id: int
    employee_id: int
    status_id: int
    start_date: str
    end_date: str | None
    note: str | None
    created_at: str
    created_by_account_id: int | None


@dataclass(frozen=True)
class StatusCorrectionRecord:
    id: int
    status_history_id: int
    field_name: str
    old_value: str | None
    new_value: str | None
    reason: str
    created_at: str
    created_by_account_id: int | None


class StatusHistoryRepository(_AppendOnlyGuard):
    table_name = "status_history"

    def __init__(self, conn: Connection) -> None:
        super().__init__(conn)

    def list_for_employee(self, employee_id: int) -> list[StatusHistoryRecord]:
        rows = self._conn.execute(
            "SELECT id, employee_id, status_id, start_date, end_date, note,"
            " created_at, created_by_account_id"
            " FROM status_history WHERE employee_id = ? ORDER BY start_date, id",
            (employee_id,),
        ).fetchall()
        return [_history_row(r) for r in rows]

    def add(
        self,
        *,
        employee_id: int,
        status_id: int,
        start_date: str,
        created_at: str,
        end_date: str | None = None,
        note: str | None = None,
        created_by_account_id: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO status_history ("
            " employee_id, status_id, start_date, end_date, note,"
            " created_at, created_by_account_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                employee_id,
                status_id,
                start_date,
                end_date,
                note,
                created_at,
                created_by_account_id,
            ),
        )
        return int(cur.lastrowid)


class StatusHistoryCorrectionRepository(_AppendOnlyGuard):
    table_name = "status_history_corrections"

    def __init__(self, conn: Connection) -> None:
        super().__init__(conn)

    def list_for_employee(self, employee_id: int) -> list[StatusCorrectionRecord]:
        rows = self._conn.execute(
            "SELECT c.id, c.status_history_id, c.field_name, c.old_value, c.new_value,"
            " c.reason, c.created_at, c.created_by_account_id"
            " FROM status_history_corrections c"
            " JOIN status_history h ON h.id = c.status_history_id"
            " WHERE h.employee_id = ?"
            " ORDER BY c.created_at, c.id",
            (employee_id,),
        ).fetchall()
        return [_correction_row(r) for r in rows]

    def add(
        self,
        *,
        status_history_id: int,
        field_name: str,
        old_value: str | None,
        new_value: str | None,
        reason: str,
        created_at: str,
        created_by_account_id: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO status_history_corrections ("
            " status_history_id, field_name, old_value, new_value, reason,"
            " created_at, created_by_account_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                status_history_id,
                field_name,
                old_value,
                new_value,
                reason,
                created_at,
                created_by_account_id,
            ),
        )
        return int(cur.lastrowid)


def _history_row(row: tuple[object, ...]) -> StatusHistoryRecord:
    return StatusHistoryRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        employee_id=int(row[1]),  # type: ignore[arg-type]
        status_id=int(row[2]),  # type: ignore[arg-type]
        start_date=str(row[3]),
        end_date=str(row[4]) if row[4] is not None else None,
        note=str(row[5]) if row[5] is not None else None,
        created_at=str(row[6]),
        created_by_account_id=int(row[7]) if row[7] is not None else None,  # type: ignore[arg-type]
    )


def _correction_row(row: tuple[object, ...]) -> StatusCorrectionRecord:
    return StatusCorrectionRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        status_history_id=int(row[1]),  # type: ignore[arg-type]
        field_name=str(row[2]),
        old_value=str(row[3]) if row[3] is not None else None,
        new_value=str(row[4]) if row[4] is not None else None,
        reason=str(row[5]),
        created_at=str(row[6]),
        created_by_account_id=int(row[7]) if row[7] is not None else None,  # type: ignore[arg-type]
    )


__all__ = [
    "AppendOnlyViolation",
    "StatusCorrectionRecord",
    "StatusHistoryCorrectionRepository",
    "StatusHistoryRecord",
    "StatusHistoryRepository",
]
