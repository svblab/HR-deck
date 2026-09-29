"""EPIC-018 conversion wizard: Save/Skip orchestration (ADR-0012)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data.db import Connection
from data.import_sessions import ImportSessionRepository
from domain.employee import EmployeeCreateInput, EmployeeValidationError
from domain.permissions import Permission
from services.authorization import AuthorizationError, AuthorizationService
from services.backup import BackupError, BackupService
from services.employees import EmployeeError, EmployeeService
from services.session import SessionState


class EmployeeConversionError(Exception):
    """Ошибка сохранения или пропуска строки конвертации."""


@dataclass(frozen=True)
class ConversionBulkSaveItemResult:
    row_id: int
    employee_id: int | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ConversionBulkSaveResult:
    results: tuple[ConversionBulkSaveItemResult, ...]

    @property
    def applied_count(self) -> int:
        return sum(1 for item in self.results if item.employee_id is not None)

    @property
    def error_count(self) -> int:
        return sum(1 for item in self.results if item.error_message)


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
        db_path: Path | str | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._employees = employees
        self._sessions = sessions or ImportSessionRepository(conn)
        self._authz = authz or AuthorizationService()
        self._db_path = Path(db_path) if db_path is not None else None
        self._pre_conversion_backup_done = False

    @property
    def session_backup_created(self) -> bool:
        return self._pre_conversion_backup_done

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
        self._ensure_pre_conversion_backup()
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

    def save_rows_bulk(
        self,
        *,
        session_id: int,
        resolved_rows: list[tuple[int, EmployeeCreateInput]],
        last_accessed_at: str,
    ) -> ConversionBulkSaveResult:
        """Apply multiple staged rows; each row uses existing save_row semantics."""
        outcomes: list[ConversionBulkSaveItemResult] = []
        for row_id, data in resolved_rows:
            try:
                employee_id = self.save_row(
                    session_id=session_id,
                    row_id=row_id,
                    data=data,
                    last_accessed_at=last_accessed_at,
                )
            except (
                EmployeeConversionError,
                EmployeeError,
                EmployeeValidationError,
            ) as exc:
                outcomes.append(
                    ConversionBulkSaveItemResult(
                        row_id=row_id, error_message=str(exc)
                    )
                )
            except Exception as exc:  # noqa: BLE001 — bulk must continue after any row failure
                outcomes.append(
                    ConversionBulkSaveItemResult(
                        row_id=row_id, error_message=str(exc)
                    )
                )
            else:
                outcomes.append(
                    ConversionBulkSaveItemResult(
                        row_id=row_id, employee_id=employee_id
                    )
                )
        return ConversionBulkSaveResult(results=tuple(outcomes))

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

    def _ensure_pre_conversion_backup(self) -> None:
        if self._pre_conversion_backup_done:
            return
        if self._db_path is None:
            raise EmployeeConversionError("database path is required for pre-conversion backup")
        backup = BackupService(
            self._conn,
            self._session,
            db_path=self._db_path,
            authz=self._authz,
        )
        try:
            backup.create_pre_apply_backup(
                "pre-conversion", log_event="backup.pre_conversion"
            )
        except BackupError as exc:
            raise EmployeeConversionError(str(exc)) from exc
        self._pre_conversion_backup_done = True

    def _require_row(self, session_id: int, row_id: int) -> None:
        for row in self._sessions.list_rows(session_id):
            if row.id == row_id:
                return
        raise EmployeeConversionError("staged row not found for session")

    def _require(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)
        self._authz.require(self._session.role, Permission.MANAGE_EMPLOYEES)


__all__ = [
    "AuthorizationError",
    "ConversionBulkSaveItemResult",
    "ConversionBulkSaveResult",
    "EmployeeConversionError",
    "EmployeeConversionService",
]
