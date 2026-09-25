"""EPIC-018: ingest conversion source files into import session staging (ADR-0012)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from data.db import Connection
from data.import_sessions import ImportSessionRepository
from domain.import_conversion import build_staged_row_values, file_content_hash
from domain.permissions import Permission
from services.authorization import AuthorizationError, AuthorizationService
from services.employee_files import EmployeeFileError, read_tabular
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ImportConversionIngestError(Exception):
    """Ошибка чтения файла или постановки строк в очередь конвертации."""


@dataclass(frozen=True)
class ImportConversionIngestResult:
    session_id: int
    file_content_hash: str
    resumed: bool
    staged_row_count: int


class ImportConversionIngestService:
    """Read XLSX/CSV, hash raw bytes, resume or create import_sessions staging."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        sessions: ImportSessionRepository | None = None,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._sessions = sessions or ImportSessionRepository(conn)
        self._authz = authz or AuthorizationService()
        self._clock: Clock = clock or _utc_now

    def ingest_file(self, source_path: Path | str) -> ImportConversionIngestResult:
        self._require()
        path = Path(source_path)
        try:
            raw_bytes = path.read_bytes()
        except OSError as exc:
            raise ImportConversionIngestError(str(exc)) from exc

        digest = file_content_hash(raw_bytes)
        existing = self._sessions.get_by_file_content_hash(digest)
        if existing is not None:
            pending = self._sessions.list_rows(existing.id)
            if pending:
                return ImportConversionIngestResult(
                    session_id=existing.id,
                    file_content_hash=digest,
                    resumed=True,
                    staged_row_count=len(pending),
                )
            self._sessions.delete_empty_session(existing.id)

        try:
            headers, rows = read_tabular(path)
        except EmployeeFileError as exc:
            raise ImportConversionIngestError(str(exc)) from exc

        staged = build_staged_row_values(headers, rows)
        now = self._clock()
        try:
            session_id = self._sessions.create_session(
                file_content_hash=digest,
                last_accessed_at=now,
            )
            for source_row_number, values in staged:
                self._sessions.insert_row(
                    session_id=session_id,
                    source_row_number=source_row_number,
                    values_json=json.dumps(values, ensure_ascii=False),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return ImportConversionIngestResult(
            session_id=session_id,
            file_content_hash=digest,
            resumed=False,
            staged_row_count=len(staged),
        )

    def _require(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)
        self._authz.require(self._session.role, Permission.MANAGE_EMPLOYEES)


__all__ = [
    "AuthorizationError",
    "ImportConversionIngestError",
    "ImportConversionIngestResult",
    "ImportConversionIngestService",
]
