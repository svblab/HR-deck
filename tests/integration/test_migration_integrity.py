"""Жёсткие правила версий и checksum миграций (EPIC-002 hardening)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import DatabaseError, connect, create_database, generate_master_key, table_columns
from data.migrations import (
    apply_pending_migrations,
    current_version,
    default_migrations_dir,
    discover_migrations,
)


def _copy_real_migrations(dst: Path, up_to: int | None = None) -> None:
    src = default_migrations_dir()
    for path in sorted(src.glob("*.sql")):
        version = int(path.name[:4])
        if up_to is not None and version > up_to:
            continue
        shutil.copy(path, dst / path.name)


@pytest.mark.acceptance
def test_discover_rejects_duplicate_version(tmp_path: Path) -> None:
    _copy_real_migrations(tmp_path, up_to=1)
    (tmp_path / "0001_duplicate.sql").write_text("-- dup\nSELECT 1;\n", encoding="utf-8")
    with pytest.raises(DatabaseError, match="duplicate"):
        discover_migrations(tmp_path)


@pytest.mark.acceptance
def test_discover_rejects_missing_version_gap(tmp_path: Path) -> None:
    _copy_real_migrations(tmp_path, up_to=1)
    (tmp_path / "0003_skip.sql").write_text(
        "ALTER TABLE schema_migrations ADD COLUMN checksum TEXT;\n",
        encoding="utf-8",
    )
    with pytest.raises(DatabaseError, match="missing migration"):
        discover_migrations(tmp_path)


@pytest.mark.acceptance
def test_apply_multiple_migrations_sequentially(tmp_path: Path) -> None:
    key = generate_master_key()
    db_path = tmp_path / "app.db"
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_real_migrations(mig_dir)

    conn = create_database(db_path, key)
    applied = apply_pending_migrations(conn, mig_dir)
    assert applied == [1, 2, 3, 4]
    assert current_version(conn) == 4
    assert "checksum" in table_columns(conn, "schema_migrations")
    rows = conn.execute(
        "SELECT version, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert len(rows) == 4
    assert all(r[1] for r in rows)
    conn.close()


@pytest.mark.acceptance
def test_reapply_is_noop(tmp_path: Path) -> None:
    key = generate_master_key()
    db_path = tmp_path / "app.db"
    conn = create_database(db_path, key)
    first = apply_pending_migrations(conn)
    second = apply_pending_migrations(conn)
    assert first == [1, 2, 3, 4]
    assert second == []
    conn.close()


@pytest.mark.acceptance
def test_failed_migration_rolls_back(tmp_path: Path) -> None:
    key = generate_master_key()
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_real_migrations(mig_dir, up_to=1)

    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn, mig_dir)
    assert current_version(conn) == 1

    (mig_dir / "0002_bad.sql").write_text(
        "CREATE TABLE should_not_remain(id INTEGER PRIMARY KEY);\n"
        "INSERT INTO missing_table(id) VALUES (1);\n",
        encoding="utf-8",
    )
    with pytest.raises(sqlcipher.DatabaseError):
        apply_pending_migrations(conn, mig_dir)

    assert current_version(conn) == 1
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'should_not_remain'"
    ).fetchone()
    assert row is None
    conn.close()


@pytest.mark.acceptance
def test_checksum_mismatch_rejected(tmp_path: Path) -> None:
    key = generate_master_key()
    db_path = tmp_path / "app.db"
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_real_migrations(mig_dir)

    conn = create_database(db_path, key)
    apply_pending_migrations(conn, mig_dir)
    conn.close()

    path_0001 = next(mig_dir.glob("0001_*.sql"))
    path_0001.write_text(
        path_0001.read_text(encoding="utf-8") + "\n-- tampered\n",
        encoding="utf-8",
    )

    conn2 = connect(db_path, key)
    with pytest.raises(DatabaseError, match="checksum mismatch"):
        apply_pending_migrations(conn2, mig_dir)
    conn2.close()
