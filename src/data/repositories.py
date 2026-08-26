"""Инфраструктура репозиториев: базовый доступ и запрет мутаций журналов."""

from __future__ import annotations

from data.db import Connection


class AppendOnlyViolation(Exception):
    """Попытка изменить/удалить запись в append-only журнале (ANCHOR_CORE A9)."""


class AppendOnlyRepository:
    """
    База для status_history и user_action_log.

    Update/delete через этот слой запрещены — только insert и выборки.
    """

    table_name: str = ""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(self, columns: dict[str, object]) -> int:
        if not columns:
            raise ValueError("columns must not be empty")
        keys = ", ".join(columns.keys())
        placeholders = ", ".join("?" for _ in columns)
        cur = self._conn.execute(
            f"INSERT INTO {self.table_name} ({keys}) VALUES ({placeholders})",
            tuple(columns.values()),
        )
        return int(cur.lastrowid)

    def update(self, *_args: object, **_kwargs: object) -> None:
        raise AppendOnlyViolation(f"{self.table_name} is append-only: update is not allowed")

    def delete(self, *_args: object, **_kwargs: object) -> None:
        raise AppendOnlyViolation(f"{self.table_name} is append-only: delete is not allowed")


class StatusHistoryRepository(AppendOnlyRepository):
    table_name = "status_history"


class UserActionLogRepository(AppendOnlyRepository):
    table_name = "user_action_log"


class TechnicalEventRepository:
    """Журнал технических событий — без паролей (запись только на добавление)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(self, event_type: str, message: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO technical_events (event_type, message, created_at) VALUES (?, ?, ?)",
            (event_type, message, created_at),
        )
        return int(cur.lastrowid)

    def update(self, *_args: object, **_kwargs: object) -> None:
        raise AppendOnlyViolation("technical_events is append-only: update is not allowed")

    def delete(self, *_args: object, **_kwargs: object) -> None:
        raise AppendOnlyViolation("technical_events is append-only: delete is not allowed")
