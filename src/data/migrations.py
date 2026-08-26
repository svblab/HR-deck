"""Версионированные миграции схемы (ANCHOR_CORE A11 / ТЗ §5)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from data.db import Connection, DatabaseError, table_columns
from data.sql_script import execute_script_transactional

_MIGRATION_NAME = re.compile(r"^(\d{4})_.+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    path: Path
    sql: str
    checksum: str

    @classmethod
    def from_path(cls, path: Path) -> Migration:
        match = _MIGRATION_NAME.match(path.name)
        if not match:
            raise DatabaseError(f"invalid migration filename: {path.name}")
        # Checksum = SHA-256 of exact file bytes (stable UTF-8 SQL on disk).
        raw = path.read_bytes()
        try:
            sql = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DatabaseError(f"migration is not valid UTF-8: {path.name}") from exc
        checksum = hashlib.sha256(raw).hexdigest()
        return cls(version=int(match.group(1)), path=path, sql=sql, checksum=checksum)


def default_migrations_dir() -> Path:
    """Каталог /migrations в корне репозитория (рядом с pyproject.toml)."""
    return Path(__file__).resolve().parents[2] / "migrations"


def discover_migrations(migrations_dir: Path | None = None) -> list[Migration]:
    root = migrations_dir or default_migrations_dir()
    if not root.is_dir():
        raise DatabaseError(f"migrations directory not found: {root}")

    found: list[Migration] = []
    seen: set[int] = set()
    for path in sorted(root.glob("*.sql")):
        if not _MIGRATION_NAME.match(path.name):
            continue
        migration = Migration.from_path(path)
        if migration.version in seen:
            raise DatabaseError(f"duplicate migration version: {migration.version:04d}")
        seen.add(migration.version)
        found.append(migration)

    found.sort(key=lambda m: m.version)
    if not found:
        return found

    versions = [m.version for m in found]
    if versions[0] != 1:
        raise DatabaseError(f"migrations must start at 0001, found {versions[0]:04d}")
    for expected, actual in enumerate(versions, start=1):
        if actual != expected:
            raise DatabaseError(
                f"missing migration version {expected:04d} (found gap before {actual:04d})"
            )
    return found


def current_version(conn: Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0]) if row else 0


def _has_checksum_column(conn: Connection) -> bool:
    return "checksum" in table_columns(conn, "schema_migrations")


def expected_migration_versions(migrations_dir: Path | None = None) -> list[int]:
    """Ожидаемая непрерывная последовательность версий из каталога миграций."""
    return [m.version for m in discover_migrations(migrations_dir)]


def repair_missing_checksums(conn: Connection, migrations: list[Migration]) -> list[int]:
    """
    Явный one-time upgrade: заполнить NULL/пустой checksum из файлов на диске.

    Вызывается только когда колонка checksum уже есть (после 0003).
    Не маскирует mismatch — только отсутствие сохранённого значения.
    """
    if current_version(conn) == 0 or not _has_checksum_column(conn):
        return []

    by_version = {m.version: m for m in migrations}
    repaired: list[int] = []
    rows = conn.execute(
        "SELECT version, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    for version, stored in rows:
        ver = int(version)
        if stored:
            continue
        migration = by_version.get(ver)
        if migration is None:
            raise DatabaseError(
                f"applied migration {ver:04d} has no matching file on disk"
            )
        conn.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = ?",
            (migration.checksum, ver),
        )
        repaired.append(ver)
    if repaired:
        conn.commit()
    return repaired


def verify_applied_checksums(conn: Connection, migrations: list[Migration]) -> None:
    """Сверка checksum уже применённых миграций с файлами на диске."""
    if current_version(conn) == 0:
        return
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None or not _has_checksum_column(conn):
        return

    by_version = {m.version: m for m in migrations}
    rows = conn.execute(
        "SELECT version, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    for version, stored in rows:
        ver = int(version)
        migration = by_version.get(ver)
        if migration is None:
            raise DatabaseError(
                f"applied migration {ver:04d} has no matching file on disk"
            )
        if not stored:
            raise DatabaseError(
                f"applied migration {ver:04d} has no checksum stored "
                "(run repair_missing_checksums or re-apply from backup)"
            )
        if stored != migration.checksum:
            raise DatabaseError(
                f"checksum mismatch for migration {ver:04d}: "
                "historical SQL was changed after apply"
            )


def apply_pending_migrations(
    conn: Connection,
    migrations_dir: Path | None = None,
) -> list[int]:
    """
    Применить все ещё не применённые миграции.

    Каждая миграция коммитится отдельно; ошибка откатывает только её.
    Нельзя применить N+1, если N отсутствует (гарантируется discover + current).
    """
    migrations = discover_migrations(migrations_dir)
    if _has_checksum_column(conn):
        repair_missing_checksums(conn, migrations)
        verify_applied_checksums(conn, migrations)

    applied: list[int] = []
    version = current_version(conn)

    for migration in migrations:
        if migration.version <= version:
            continue
        if migration.version != version + 1:
            raise DatabaseError(
                f"cannot apply migration {migration.version:04d}: "
                f"expected next version {version + 1:04d}"
            )
        try:
            previous_isolation = conn.isolation_level
            conn.isolation_level = None
            conn.execute("BEGIN")
            try:
                execute_script_transactional(conn, migration.sql)
                exists = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='schema_migrations'"
                ).fetchone()
                if exists is None:
                    raise DatabaseError(
                        f"migration {migration.version:04d} did not create schema_migrations"
                    )
                now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                if _has_checksum_column(conn):
                    conn.execute(
                        "INSERT INTO schema_migrations (version, checksum, applied_at) "
                        "VALUES (?, ?, ?)",
                        (migration.version, migration.checksum, now),
                    )
                else:
                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                        (migration.version, now),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.isolation_level = previous_isolation

            applied.append(migration.version)
            version = migration.version
            if _has_checksum_column(conn):
                repair_missing_checksums(conn, migrations)
                verify_applied_checksums(conn, migrations)
        except Exception:
            raise
    return applied
