"""Persistence for EPIC-018 conversion staging (ADR-0012)."""

from __future__ import annotations

from dataclasses import dataclass

from data.db import Connection


@dataclass(frozen=True)
class ImportSessionRecord:
    id: int
    file_content_hash: str
    last_accessed_at: str


@dataclass(frozen=True)
class ImportSessionRowRecord:
    id: int
    session_id: int
    source_row_number: int
    values_json: str


class ImportSessionRepository:
    """SQL adapter for import_sessions / import_session_rows. No business logic."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create_session(self, *, file_content_hash: str, last_accessed_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO import_sessions (file_content_hash, last_accessed_at)"
            " VALUES (?, ?)",
            (file_content_hash, last_accessed_at),
        )
        return int(cur.lastrowid)

    def get_by_file_content_hash(self, file_content_hash: str) -> ImportSessionRecord | None:
        row = self._conn.execute(
            "SELECT id, file_content_hash, last_accessed_at"
            " FROM import_sessions WHERE file_content_hash = ?",
            (file_content_hash,),
        ).fetchone()
        return _session_row(row) if row else None

    def list_rows(self, session_id: int) -> list[ImportSessionRowRecord]:
        rows = self._conn.execute(
            "SELECT id, session_id, source_row_number, values_json"
            " FROM import_session_rows WHERE session_id = ?"
            " ORDER BY source_row_number ASC",
            (session_id,),
        ).fetchall()
        return [_pending_row(r) for r in rows]

    def insert_row(
        self,
        *,
        session_id: int,
        source_row_number: int,
        values_json: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO import_session_rows (session_id, source_row_number, values_json)"
            " VALUES (?, ?, ?)",
            (session_id, source_row_number, values_json),
        )
        return int(cur.lastrowid)

    def delete_row(self, row_id: int) -> None:
        self._conn.execute("DELETE FROM import_session_rows WHERE id = ?", (row_id,))

    def touch_session(self, session_id: int, *, last_accessed_at: str) -> None:
        self._conn.execute(
            "UPDATE import_sessions SET last_accessed_at = ? WHERE id = ?",
            (last_accessed_at, session_id),
        )

    def delete_empty_session(self, session_id: int) -> bool:
        """Remove session only when it has no staged rows. Does not delete pending rows."""
        pending = self._conn.execute(
            "SELECT COUNT(*) FROM import_session_rows WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if pending is None or int(pending[0]) > 0:
            return False
        cur = self._conn.execute("DELETE FROM import_sessions WHERE id = ?", (session_id,))
        return int(cur.rowcount) > 0

    def purge_all(self) -> None:
        self._conn.execute("DELETE FROM import_sessions")

    def delete_stale_before(self, cutoff_last_accessed_at: str) -> int:
        """Delete sessions with last_accessed_at strictly before cutoff (cascade rows)."""
        cur = self._conn.execute(
            "DELETE FROM import_sessions WHERE last_accessed_at < ?",
            (cutoff_last_accessed_at,),
        )
        return int(cur.rowcount)


def _session_row(row: tuple[object, ...]) -> ImportSessionRecord:
    return ImportSessionRecord(
        id=int(row[0]),
        file_content_hash=str(row[1]),
        last_accessed_at=str(row[2]),
    )


def _pending_row(row: tuple[object, ...]) -> ImportSessionRowRecord:
    return ImportSessionRowRecord(
        id=int(row[0]),
        session_id=int(row[1]),
        source_row_number=int(row[2]),
        values_json=str(row[3]),
    )


__all__ = [
    "ImportSessionRecord",
    "ImportSessionRepository",
    "ImportSessionRowRecord",
]
