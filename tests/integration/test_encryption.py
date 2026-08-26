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


def _create_migrated(path: Path, key: bytes):
    conn = create_database(path, key)
    apply_pending_migrations(conn)
    conn.execute(
        "INSERT INTO branches (name, is_archived, created_at, updated_at) VALUES (?, 0, ?, ?)",
        ("Секретный филиал", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()


@pytest.mark.acceptance
def test_database_file_is_not_plaintext_sqlite(tmp_path: Path) -> None:
    """ТЗ §11: БД хранится зашифрованной — заголовок не 'SQLite format 3'."""
    key = generate_master_key()
    path = tmp_path / "app.db"
    _create_migrated(path, key)

    raw = path.read_bytes()
    assert b"SQLite format 3" not in raw[:32]
    assert "Секретный филиал".encode() not in raw
    assert not file_looks_unencrypted(path)


@pytest.mark.acceptance
def test_wrong_master_key_denied(tmp_path: Path) -> None:
    """ТЗ §11: без верного ключа данные недоступны."""
    key = generate_master_key()
    path = tmp_path / "app.db"
    _create_migrated(path, key)

    with pytest.raises((DatabaseError, IntegrityError)):
        connect(path, generate_master_key())


@pytest.mark.acceptance
def test_correct_key_reopen_after_close(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    _create_migrated(path, key)

    conn = connect(path, key, check_integrity=True)
    assert current_version(conn) >= 1
    name = conn.execute("SELECT name FROM branches LIMIT 1").fetchone()[0]
    assert name == "Секретный филиал"
    conn.close()

    conn2 = connect(path, key, check_integrity=True)
    assert conn2.execute("SELECT COUNT(*) FROM branches").fetchone()[0] == 1
    conn2.close()


@pytest.mark.acceptance
def test_truncated_database_rejected(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    _create_migrated(path, key)
    data = path.read_bytes()
    path.write_bytes(data[:64])

    with pytest.raises((DatabaseError, IntegrityError, Exception)):
        connect(path, key)


@pytest.mark.acceptance
def test_corrupted_database_rejected(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    _create_migrated(path, key)
    data = bytearray(path.read_bytes())
    # Портим середину файла (не заголовок целиком).
    mid = max(len(data) // 2, 100)
    for i in range(mid, min(mid + 64, len(data))):
        data[i] ^= 0xFF
    path.write_bytes(bytes(data))

    with pytest.raises((DatabaseError, IntegrityError, Exception)):
        connect(path, key)
