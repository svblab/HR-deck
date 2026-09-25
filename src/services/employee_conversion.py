"""EPIC-018 conversion wizard: Save/Skip orchestration (ADR-0012)."""

from __future__ import annotations

from data.db import Connection
from data.import_sessions import ImportSessionRepository
from domain.employee import EmployeeCreateInput
from domain.permissions import Permission
from services.authorization import AuthorizationError, AuthorizationService
from services.employees import EmployeeService
from services.session import SessionState


class EmployeeConversionError(Exception):
    """Ошибка сохранения или пропуска строки конвертации."""


class EmployeeConversionService:
    """Atomic Save/Skip for staged import rows; no file ingest."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        employees: EmployeeService,
        *,
        sessions: ImportSessionRepository | None = None,
        authz: AuthorizationService | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._employees = employees
        self._sessions = sessions or ImportSessionRepository(conn)
        self._authz = authz or AuthorizationService()

    def save_row(
        self,
        *,
        session_id: int,
        row_id: int,
        data: EmployeeCreateInput,
        last_accessed_at: str,
    ) -> int:
        """Create employee and remove staged row in one transaction."""
        self._require()
        self._require_row(session_id, row_id)
        try:
            employee_id = self._employees.create_employee(data, commit=False)
            self._sessions.delete_row(row_id)
            self._sessions.touch_session(session_id, last_accessed_at=last_accessed_at)
            self._sessions.delete_empty_session(session_id)
            self._conn.commit()
            return employee_id
        except Exception:
            self._conn.rollback()
            raise

    def skip_row(
        self,
        *,
        session_id: int,
        row_id: int,
        last_accessed_at: str,
    ) -> None:
        """Drop staged row without creating an employee."""
        self._require()
        self._require_row(session_id, row_id)
        try:
            self._sessions.delete_row(row_id)
            self._sessions.touch_session(session_id, last_accessed_at=last_accessed_at)
            self._sessions.delete_empty_session(session_id)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _require_row(self, session_id: int, row_id: int) -> None:
        for row in self._sessions.list_rows(session_id):
            if row.id == row_id:
                return
        raise EmployeeConversionError("staged row not found for session")

    def _require(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)
        self._authz.require(self._session.role, Permission.MANAGE_EMPLOYEES)


__all__ = ["AuthorizationError", "EmployeeConversionError", "EmployeeConversionService"]
