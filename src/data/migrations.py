"""Версионированные миграции схемы (ANCHOR_CORE A11 / ТЗ §5)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from data.db import Connection, DatabaseError, table_columns

_MIGRATION_NAME = re.compile(r"^(\d{4})_.+\.sql$")
_BEGIN = re.compile(r"\bBEGIN\b", re.IGNORECASE)
_END = re.compile(r"\bEND\b", re.IGNORECASE)


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
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        return cls(version=int(match.group(1)), path=path, sql=sql, checksum=checksum)


def default_migrations_dir() -> Path:
    """Каталог /migrations в корне репозитория (рядом с pyproject.toml)."""
    return Path(__file__).resolve().parents[2] / "migrations"


def split_sql_statements(script: str) -> list[str]:
    """
    Разбить SQL-скрипт на statements.

    Учитывает блоки BEGIN…END у триггеров; не использует executescript
    (он делает неявный COMMIT и ломает откат).
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(script)
    begin_depth = 0
    in_single = False
    in_double = False

    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""

        if not in_single and not in_double and ch == "-" and nxt == "-":
            while i < n and script[i] != "\n":
                buf.append(script[i])
                i += 1
            continue

        if not in_double and ch == "'":
            buf.append(ch)
            if in_single and nxt == "'":
                buf.append(nxt)
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue

        if not in_single and ch == '"':
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue

        if not in_single and not in_double:
            rest = script[i:]
            begin_match = _BEGIN.match(rest)
            end_match = _END.match(rest)
            if begin_match:
                token = begin_match.group(0)
                buf.append(token)
                begin_depth += 1
                i += len(token)
                continue
            if end_match and begin_depth > 0:
                token = end_match.group(0)
                buf.append(token)
                begin_depth -= 1
                i += len(token)
                continue
            if ch == ";" and begin_depth == 0:
                stmt = "".join(buf).strip()
                if stmt:
                    statements.append(stmt)
                buf = []
                i += 1
                continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def execute_script_transactional(conn: Connection, sql: str) -> None:
    """Выполнить скрипт statement-by-statement внутри текущей транзакции."""
    for statement in split_sql_statements(sql):
        conn.execute(statement)


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
    dirty = False
    for version, stored in rows:
        migration = by_version.get(int(version))
        if migration is None:
            raise DatabaseError(
                f"applied migration {int(version):04d} has no matching file on disk"
            )
        if stored is None:
            # Однократный backfill после 0003: NULL → текущий checksum файла.
            conn.execute(
                "UPDATE schema_migrations SET checksum = ? WHERE version = ? AND checksum IS NULL",
                (migration.checksum, int(version)),
            )
            dirty = True
            continue
        if stored != migration.checksum:
            raise DatabaseError(
                f"checksum mismatch for migration {int(version):04d}: "
                "historical SQL was changed after apply"
            )
    if dirty:
        conn.commit()


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
            # Явная транзакция: DDL у SQLCipher/sqlite иначе может «выпасть» из отката.
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
            verify_applied_checksums(conn, migrations)
        except Exception:
            raise
    return applied
