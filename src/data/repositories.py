"""Инфраструктура репозиториев журналов: typed insert + запрет update/delete."""

from __future__ import annotations

from data.db import Connection
from domain.action_log import ENTITY_TEMPLATE, ActionLogEntry


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

    def list_entries(
        self,
        *,
        account_id: int | None = None,
        created_from: str | None = None,
        created_to_exclusive: str | None = None,
        action_type: str | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        limit: int = 10_000,
    ) -> list[ActionLogEntry]:
        clauses: list[str] = []
        params: list[object] = []
        if account_id is not None:
            clauses.append("l.account_id = ?")
            params.append(account_id)
        if created_from is not None:
            clauses.append("l.created_at >= ?")
            params.append(created_from)
        if created_to_exclusive is not None:
            clauses.append("l.created_at < ?")
            params.append(created_to_exclusive)
        if action_type is not None:
            clauses.append("l.action_type = ?")
            params.append(action_type)
        if entity_type is not None:
            clauses.append("l.entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            clauses.append("l.entity_id = ?")
            params.append(entity_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT l.id, l.account_id, a.login, l.action_type, l.entity_type,"
            " l.entity_id, l.result, l.details, l.created_at"
            " FROM user_action_log l LEFT JOIN accounts a ON a.id = l.account_id"
            f"{where} ORDER BY l.created_at DESC, l.id DESC LIMIT ?"
        )
        params.append(limit)
        return [_entry_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def list_action_types(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT action_type FROM user_action_log ORDER BY action_type"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def list_template_refs(self) -> list[tuple[int, str]]:
        rows = self._conn.execute(
            "SELECT DISTINCT entity_id FROM user_action_log"
            " WHERE entity_type = ? AND entity_id IS NOT NULL"
            " ORDER BY entity_id",
            (ENTITY_TEMPLATE,),
        ).fetchall()
        return [(int(r[0]), str(r[0])) for r in rows]


class TechnicalEventRepository(_AppendOnlyGuard):
    """Журнал технических событий — без паролей; только добавление."""

    table_name = "technical_events"

    def record(self, *, event_type: str, message: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO technical_events (event_type, message, created_at) VALUES (?, ?, ?)",
            (event_type, message, created_at),
        )
        return int(cur.lastrowid)


def _entry_row(row: tuple[object, ...]) -> ActionLogEntry:
    return ActionLogEntry(
        id=int(row[0]),  # type: ignore[arg-type]
        account_id=None if row[1] is None else int(row[1]),  # type: ignore[arg-type]
        account_login=None if row[2] is None else str(row[2]),
        action_type=str(row[3]),
        entity_type=None if row[4] is None else str(row[4]),
        entity_id=None if row[5] is None else int(row[5]),  # type: ignore[arg-type]
        result=str(row[6]),
        details=None if row[7] is None else str(row[7]),
        created_at=str(row[8]),
    )
