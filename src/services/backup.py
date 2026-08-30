"""Резервное копирование и восстановление БД (EPIC-012, ADR-0002)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from data.backup_io import (
    backup_filename,
    checkpoint_wal,
    copy_database_pair,
    default_backups_dir,
    remove_paths,
    swap_live_from_backup,
    verify_database_file,
)
from data.db import Connection, connect
from data.keywrap import keywrap_path_for
from data.repositories import TechnicalEventRepository
from domain.permissions import Permission
from services.authorization import AuthorizationError, AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class BackupError(Exception):
    """Ошибка создания или восстановления резервной копии."""


class BackupService:
    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        db_path: Path | str,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._db_path = Path(db_path)
        self._authz = authz or AuthorizationService()
        self._clock: Clock = clock or _utc_now
        self._events = TechnicalEventRepository(conn)

    def create_backup(self, destination_dir: Path | str) -> Path:
        """Скопировать зашифрованную БД + keywrap, проверить, залогировать."""
        self._require(Permission.CREATE_BACKUP)
        dest = Path(destination_dir)
        dest.mkdir(parents=True, exist_ok=True)
        now = self._clock()
        backup_path = dest / backup_filename(now)
        self._log("backup.create", "started", now)
        self._conn.commit()
        try:
            path = self._copy_live_to(backup_path)
            verify_database_file(path, self._session.master_key)
            self._log("backup.create", f"success path={path.name}", now)
            self._conn.commit()
            return path
        except Exception as exc:
            remove_paths(backup_path, keywrap_path_for(backup_path))
            self._log("backup.create", f"failure reason={exc}", now)
            self._conn.commit()
            raise BackupError(str(exc)) from exc

    def verify_backup(self, backup_path: Path | str) -> None:
        """Проверить файл бэкапа до восстановления."""
        path = Path(backup_path)
        if not keywrap_path_for(path).is_file():
            raise BackupError("backup keywrap sidecar not found")
        verify_database_file(path, self._session.master_key)

    def restore_backup(self, backup_path: Path | str) -> Connection:
        """
        Pre-restore safety backup → verify source → atomic swap → verify live.
        Закрывает текущее соединение и возвращает новое.
        """
        self._require(Permission.RESTORE_BACKUP)
        source = Path(backup_path)
        now = self._clock()
        self._log("backup.restore", "started", now)
        self._conn.commit()
        try:
            self.verify_backup(source)
        except Exception as exc:
            self._log("backup.restore", f"verify failed reason={exc}", now)
            self._conn.commit()
            raise BackupError(str(exc)) from exc

        pre_dir = default_backups_dir(self._db_path.parent)
        try:
            pre_name = f"pre-restore-{backup_filename(now)}"
            pre_path = self._copy_live_to(pre_dir / pre_name)
            verify_database_file(pre_path, self._session.master_key)
        except Exception as exc:
            self._log("backup.restore", f"pre-backup failed reason={exc}", now)
            self._conn.commit()
            raise BackupError(f"pre-restore backup failed: {exc}") from exc

        self._conn.close()

        try:
            swap_live_from_backup(self._db_path, source)
            verify_database_file(self._db_path, self._session.master_key)
            new_conn = connect(self._db_path, self._session.master_key)
            self._conn = new_conn
            self._events = TechnicalEventRepository(new_conn)
            self._log("backup.restore", "success", now)
            self._conn.commit()
            return new_conn
        except Exception as exc:
            new_conn = connect(self._db_path, self._session.master_key)
            self._conn = new_conn
            self._events = TechnicalEventRepository(new_conn)
            self._log("backup.restore", f"failure reason={exc}", now)
            self._conn.commit()
            raise BackupError(str(exc)) from exc

    def _copy_live_to(self, destination_db: Path) -> Path:
        checkpoint_wal(self._conn)
        self._conn.commit()
        copy_database_pair(self._db_path, destination_db)
        return destination_db

    def _require(self, permission: Permission) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, permission)

    def _log(self, event_type: str, message: str, created_at: str) -> None:
        self._events.record(
            event_type=event_type,
            message=message,
            created_at=created_at,
        )


__all__ = ["AuthorizationError", "BackupError", "BackupService"]
