"""Интеграция: шифрование файла БД (ADR-0002 / TESTING §2.1, §2.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import (
    DatabaseError,
    IntegrityError,
    connect,
    create_database,
    file_looks_unencrypted,
    generate_master_key,
)
from data.migrations import apply_pending_migrations, current_version


@pytest.mark.acceptance
def test_database_file_is_not_plaintext_sqlite(tmp_path: Path) -> None:
    """ТЗ §11: БД хранится зашифрованной — заголовок не 'SQLite format 3'."""
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn)
    conn.execute(
        "INSERT INTO branches (name, is_archived, created_at, updated_at) VALUES (?, 0, ?, ?)",
        ("Секретный филиал", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    raw = path.read_bytes()
    assert b"SQLite format 3" not in raw[:32]
    assert "Секретный филиал".encode() not in raw
    assert not file_looks_unencrypted(path)


@pytest.mark.acceptance
def test_wrong_master_key_denied(tmp_path: Path) -> None:
    """ТЗ §11: без верного ключа данные недоступны."""
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn)
    conn.close()

    with pytest.raises((DatabaseError, IntegrityError)):
        connect(path, generate_master_key())


@pytest.mark.acceptance
def test_open_with_correct_key_and_integrity(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn)
    assert current_version(conn) == 1
    conn.close()

    conn2 = connect(path, key, check_integrity=True)
    assert current_version(conn2) == 1
    conn2.close()
