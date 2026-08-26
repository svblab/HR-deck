"""Версионированные миграции схемы (ANCHOR_CORE A11 / ТЗ §5)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from data.db import Connection, DatabaseError, execute_script

_MIGRATION_NAME = re.compile(r"^(\d{4})_.+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


def default_migrations_dir() -> Path:
    """Каталог /migrations в корне репозитория (рядом с pyproject.toml)."""
    # src/data/migrations.py -> src/data -> src -> repo root
    return Path(__file__).resolve().parents[2] / "migrations"


def discover_migrations(migrations_dir: Path | None = None) -> list[Migration]:
    root = migrations_dir or default_migrations_dir()
    found: list[Migration] = []
    if not root.is_dir():
        raise DatabaseError(f"migrations directory not found: {root}")
    for path in sorted(root.glob("*.sql")):
        match = _MIGRATION_NAME.match(path.name)
        if not match:
            continue
        found.append(Migration(version=int(match.group(1)), path=path))
    versions = [m.version for m in found]
    if versions != sorted(set(versions)):
        raise DatabaseError("duplicate or unsorted migration versions")
    return found


def current_version(conn: Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0]) if row else 0


def apply_pending_migrations(
    conn: Connection,
    migrations_dir: Path | None = None,
) -> list[int]:
    """
    Применить все ещё не применённые миграции в одной транзакции на файл.

    Возвращает список применённых номеров версий.
    """
    migrations = discover_migrations(migrations_dir)
    applied: list[int] = []
    version = current_version(conn)

    for migration in migrations:
        if migration.version <= version:
            continue
        try:
            execute_script(conn, migration.sql)
            exists = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if exists is None:
                raise DatabaseError(
                    f"migration {migration.version:04d} did not create schema_migrations"
                )
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (migration.version, now),
            )
            conn.commit()
            applied.append(migration.version)
            version = migration.version
        except Exception:
            conn.rollback()
            raise
    return applied
