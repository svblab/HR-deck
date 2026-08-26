"""Инфраструктура репозиториев журналов: typed insert + запрет update/delete."""

from __future__ import annotations

from data.db import Connection


class AppendOnlyViolation(Exception):
    """Попытка изменить/удалить запись в append-only журнале (ANCHOR_CORE A9)."""


class _AppendOnlyGuard:
    """Общий запрет update/delete; без универсального insert(dict)."""

    table_name: str = ""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def update(self, *_args: object, **_kwargs: object) -> None:
        raise AppendOnlyViolation(f"{self.table_name} is append-only: update is not allowed")

    def delete(self, *_args: object, **_kwargs: object) -> None:
        raise AppendOnlyViolation(f"{self.table_name} is append-only: delete is not allowed")


class StatusHistoryRepository(_AppendOnlyGuard):
    table_name = "status_history"

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


class UserActionLogRepository(_AppendOnlyGuard):
    table_name = "user_action_log"

    def record(
        self,
        *,
        action_type: str,
        result: str,
        created_at: str,
        account_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        details: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO user_action_log ("
            " account_id, action_type, entity_type, entity_id, result, details, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account_id, action_type, entity_type, entity_id, result, details, created_at),
        )
        return int(cur.lastrowid)


class TechnicalEventRepository(_AppendOnlyGuard):
    """Журнал технических событий — без паролей; только добавление."""

    table_name = "technical_events"

    def record(self, *, event_type: str, message: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO technical_events (event_type, message, created_at) VALUES (?, ?, ?)",
            (event_type, message, created_at),
        )
        return int(cur.lastrowid)
