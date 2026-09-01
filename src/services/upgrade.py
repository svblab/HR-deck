"""Безопасное обновление схемы: бэкап → миграция → откат при сбое (EPIC-015, ТЗ §8)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from data.backup_io import (
    backup_filename,
    checkpoint_wal,
    copy_database_pair,
    default_backups_dir,
    swap_live_from_backup,
    verify_database_file,
)
from data.db import Connection, connect
from data.migrations import apply_pending_migrations, current_version, discover_migrations
from data.repositories import TechnicalEventRepository
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class UpgradeError(Exception):
    """Не удалось применить миграции; live-БД восстановлена из pre-upgrade бэкапа."""


class UpgradeService:
    """
    Применяет ожидающие миграции после входа.

    Перед первой новой миграцией создаёт pre-upgrade бэкап через backup_io
    (без BackupService — не требует Permission.CREATE_BACKUP).
    При ошибке откатывает live-файлы через swap_live_from_backup.
    """

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        db_path: Path | str,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._db_path = Path(db_path)
        self._clock: Clock = clock or _utc_now
        self._events = TechnicalEventRepository(conn)

    def apply_pending(self, *, migrations_dir: Path | None = None) -> list[int]:
        migrations = discover_migrations(migrations_dir)
        if not migrations:
            return []
        if current_version(self._conn) >= migrations[-1].version:
            return []

        now = self._clock()
        self._log("upgrade.migrate", "started", now)
        self._conn.commit()

        backup_dir = default_backups_dir(self._db_path.parent)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"pre-upgrade-{backup_filename(now)}"

        try:
            checkpoint_wal(self._conn)
            self._conn.commit()
            copy_database_pair(self._db_path, backup_path)
            verify_database_file(backup_path, self._session.master_key)
        except Exception as exc:
            self._log("upgrade.migrate", f"pre-backup failed reason={exc}", now)
            self._conn.commit()
            raise UpgradeError(f"pre-upgrade backup failed: {exc}") from exc

        try:
            applied = apply_pending_migrations(self._conn, migrations_dir)
        except Exception as exc:
            self._log(
                "upgrade.migrate",
                f"failure reason={exc}; rolling back from {backup_path.name}",
                now,
            )
            self._conn.commit()
            self._conn.close()
            try:
                swap_live_from_backup(self._db_path, backup_path)
                verify_database_file(self._db_path, self._session.master_key)
                new_conn = connect(self._db_path, self._session.master_key)
                self._conn = new_conn
                self._events = TechnicalEventRepository(new_conn)
                self._log("upgrade.migrate", "rollback success", now)
                self._conn.commit()
            except Exception as rollback_exc:
                new_conn = connect(self._db_path, self._session.master_key)
                self._conn = new_conn
                self._events = TechnicalEventRepository(new_conn)
                self._log("upgrade.migrate", f"rollback failed reason={rollback_exc}", now)
                self._conn.commit()
                raise UpgradeError(
                    f"migration failed and rollback failed: {rollback_exc}"
                ) from rollback_exc
            raise UpgradeError(
                "migration failed; database restored from pre-upgrade backup"
            ) from exc

        self._log(
            "upgrade.migrate",
            f"success applied={','.join(str(v) for v in applied) or 'none'}",
            now,
        )
        self._conn.commit()
        return applied

    def _log(self, event_type: str, message: str, created_at: str) -> None:
        self._events.record(
            event_type=event_type,
            message=message,
            created_at=created_at,
        )


__all__ = ["UpgradeError", "UpgradeService"]
