"""Подключение к зашифрованной SQLite (SQLCipher) по ADR-0002."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlcipher3 import dbapi2 as sqlcipher

MASTER_KEY_BYTES = 32


class DatabaseError(Exception):
    """Ошибка открытия, расшифровки или целостности БД."""


class IntegrityError(DatabaseError):
    """Файл БД повреждён или ключ неверный (не проходит проверку целостности)."""


def generate_master_key() -> bytes:
    """Сгенерировать новый мастер-ключ шифрования БД (не пароль учётной записи)."""
    return secrets.token_bytes(MASTER_KEY_BYTES)


def _pragma_key_sql(master_key: bytes) -> str:
    if len(master_key) != MASTER_KEY_BYTES:
        raise ValueError(f"master_key must be {MASTER_KEY_BYTES} bytes")
    return f"PRAGMA key = \"x'{master_key.hex()}'\""


def _apply_key(conn: sqlcipher.Connection, master_key: bytes) -> None:
    conn.execute(_pragma_key_sql(master_key))
    # Рекомендуемые параметры SQLCipher 4 (совместимость новых БД).
    conn.execute("PRAGMA cipher_compatibility = 4")


def verify_integrity(conn: sqlcipher.Connection) -> None:
    """
    Проверить целостность зашифрованной БД.

    Пустой результат PRAGMA cipher_integrity_check — успех.
    При неверном ключе / порче файла SQLCipher возвращает ошибки или строки.
    """
    try:
        rows = conn.execute("PRAGMA cipher_integrity_check").fetchall()
    except sqlcipher.DatabaseError as exc:
        raise IntegrityError("cipher integrity check failed") from exc
    if rows:
        details = "; ".join(str(r[0]) for r in rows)
        raise IntegrityError(f"cipher integrity check failed: {details}")


def connect(
    path: Path | str,
    master_key: bytes,
    *,
    check_integrity: bool = True,
) -> sqlcipher.Connection:
    """
    Открыть существующий файл БД с мастер-ключом.

    Raises:
        DatabaseError / IntegrityError: неверный ключ или повреждённый файл.
    """
    db_path = Path(path)
    if not db_path.is_file():
        raise DatabaseError(f"database file not found: {db_path}")

    conn = sqlcipher.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _apply_key(conn, master_key)
        # Принудительно трогаем схему — при неверном ключе упадём здесь.
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        if check_integrity:
            verify_integrity(conn)
    except IntegrityError:
        conn.close()
        raise
    except sqlcipher.DatabaseError as exc:
        conn.close()
        raise DatabaseError("cannot open database with provided master key") from exc
    return conn


def create_database(path: Path | str, master_key: bytes) -> sqlcipher.Connection:
    """Создать новый зашифрованный файл БД (пустая схема до миграций)."""
    db_path = Path(path)
    if db_path.exists():
        raise DatabaseError(f"database already exists: {db_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlcipher.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _apply_key(conn, master_key)
    # Материализуем заголовок SQLCipher.
    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    conn.commit()
    verify_integrity(conn)
    return conn


@contextmanager
def database_session(
    path: Path | str,
    master_key: bytes,
    *,
    check_integrity: bool = True,
) -> Iterator[sqlcipher.Connection]:
    """Контекстный менеджер: открыть БД и гарантированно закрыть соединение."""
    conn = connect(path, master_key, check_integrity=check_integrity)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def file_looks_unencrypted(path: Path | str) -> bool:
    """Грубая проверка: обычный SQLite начинается с 'SQLite format 3'."""
    header = Path(path).read_bytes()[:16]
    return header.startswith(b"SQLite format 3")


def execute_script(conn: sqlcipher.Connection, sql: str) -> None:
    """Выполнить SQL-скрипт (несколько statements)."""
    conn.executescript(sql)


def fetch_table_names(conn: sqlcipher.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(r[0]) for r in rows}


def table_columns(conn: sqlcipher.Connection, table: str) -> set[str]:
    # table name from our migrations only — not user input in production callers.
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


Connection = sqlcipher.Connection
AnyCursor = Any
