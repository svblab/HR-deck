"""Checksum миграций: запись, сверка, mismatch, повторный запуск (P0-2)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from data.db import DatabaseError, connect, create_database, generate_master_key
from data.migrations import (
    Migration,
    apply_pending_migrations,
    current_version,
    default_migrations_dir,
    discover_migrations,
    expected_migration_versions,
    repair_missing_checksums,
    verify_applied_checksums,
)


def _copy_migs(dst: Path) -> list[int]:
    src = default_migrations_dir()
    for path in sorted(src.glob("*.sql")):
        shutil.copy(path, dst / path.name)
    return expected_migration_versions(dst)


@pytest.mark.acceptance
def test_checksum_written_and_matches_file_bytes(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    expected = _copy_migs(mig_dir)
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    applied = apply_pending_migrations(conn, mig_dir)
    assert applied == expected
    assert current_version(conn) == expected[-1]

    disk = {m.version: m for m in discover_migrations(mig_dir)}
    rows = conn.execute(
        "SELECT version, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert [r[0] for r in rows] == expected
    for version, checksum in rows:
        assert checksum
        assert checksum == disk[int(version)].checksum
        raw = next(mig_dir.glob(f"{int(version):04d}_*.sql")).read_bytes()
        assert checksum == hashlib.sha256(raw).hexdigest()
    conn.close()


@pytest.mark.acceptance
def test_checksum_mismatch_on_tampered_applied_migration(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_migs(mig_dir)
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn, mig_dir)
    conn.close()

    target = next(mig_dir.glob("0002_*.sql"))
    target.write_bytes(target.read_bytes() + b"\n-- tampered\n")

    conn2 = connect(path, key)
    with pytest.raises(DatabaseError, match="checksum mismatch"):
        apply_pending_migrations(conn2, mig_dir)
    conn2.close()


@pytest.mark.acceptance
def test_new_migration_applies_with_checksum(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    # Только до 0004, затем добавим 0005 вручную как «новую».
    src = default_migrations_dir()
    for path in sorted(src.glob("*.sql")):
        if int(path.name[:4]) <= 4:
            shutil.copy(path, mig_dir / path.name)

    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn, mig_dir)
    assert current_version(conn) == 4

    (mig_dir / "0005_extra.sql").write_text(
        "CREATE TABLE checksum_probe(id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    applied = apply_pending_migrations(conn, mig_dir)
    assert applied == [5]
    row = conn.execute(
        "SELECT checksum FROM schema_migrations WHERE version = 5"
    ).fetchone()
    assert row is not None and row[0]
    assert row[0] == Migration.from_path(mig_dir / "0005_extra.sql").checksum
    conn.close()


@pytest.mark.acceptance
def test_verify_rejects_missing_checksum_without_repair(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_migs(mig_dir)
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn, mig_dir)
    conn.execute("UPDATE schema_migrations SET checksum = NULL WHERE version = 1")
    conn.commit()
    migrations = discover_migrations(mig_dir)
    with pytest.raises(DatabaseError, match="no checksum stored"):
        verify_applied_checksums(conn, migrations)
    repaired = repair_missing_checksums(conn, migrations)
    assert 1 in repaired
    verify_applied_checksums(conn, migrations)
    conn.close()
