"""Applied migration sequence + explicit legacy checksum repair."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from data.db import DatabaseError, connect, create_database, generate_master_key
from data.migrations import (
    apply_pending_migrations,
    current_version,
    default_migrations_dir,
    discover_migrations,
    expected_migration_versions,
    repair_missing_checksums,
    validate_applied_migrations,
)


def _copy_migs(dst: Path, up_to: int | None = None) -> list[int]:
    src = default_migrations_dir()
    for path in sorted(src.glob("*.sql")):
        version = int(path.name[:4])
        if up_to is not None and version > up_to:
            continue
        shutil.copy(path, dst / path.name)
    return expected_migration_versions(dst)


@pytest.mark.acceptance
def test_applied_versions_gap_rejected(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_migs(mig_dir)
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn, mig_dir)

    conn.execute("DELETE FROM schema_migrations WHERE version = 3")
    conn.commit()
    # MAX would say 5 (or latest), but history has a hole.
    assert current_version(conn) >= 4

    migrations = discover_migrations(mig_dir)
    with pytest.raises(DatabaseError, match="gap in applied migrations"):
        validate_applied_migrations(conn, migrations)
    with pytest.raises(DatabaseError, match="gap in applied migrations"):
        apply_pending_migrations(conn, mig_dir)
    conn.close()


@pytest.mark.acceptance
def test_applied_version_without_file_rejected(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_migs(mig_dir)
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn, mig_dir)

    migrations = [m for m in discover_migrations(mig_dir) if m.version != 2]
    with pytest.raises(DatabaseError, match="no matching file"):
        validate_applied_migrations(conn, migrations)
    conn.close()


@pytest.mark.acceptance
def test_applied_version_above_discovered_latest_rejected(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_migs(mig_dir, up_to=3)
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn, mig_dir)
    assert current_version(conn) == 3

    # Continuous 1..4 in DB while disk only has 1..3 → exceeds latest (not a gap).
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO schema_migrations (version, checksum, applied_at) "
        "VALUES (4, 'deadbeef', ?)",
        (now,),
    )
    conn.commit()

    migrations = discover_migrations(mig_dir)
    with pytest.raises(DatabaseError, match="exceeds latest discovered"):
        validate_applied_migrations(conn, migrations)
    conn.close()


@pytest.mark.acceptance
def test_legacy_null_checksum_requires_explicit_repair(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_migs(mig_dir)
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn, mig_dir)
    conn.execute("UPDATE schema_migrations SET checksum = NULL WHERE version = 1")
    conn.commit()
    conn.close()

    migrations = discover_migrations(mig_dir)
    conn2 = connect(path, key)
    with pytest.raises(DatabaseError, match="no checksum stored"):
        validate_applied_migrations(conn2, migrations)
    with pytest.raises(DatabaseError, match="no checksum stored"):
        apply_pending_migrations(conn2, mig_dir)

    repaired = repair_missing_checksums(conn2, migrations)
    assert 1 in repaired
    validate_applied_migrations(conn2, migrations)
    assert apply_pending_migrations(conn2, mig_dir) == []
    conn2.close()


@pytest.mark.acceptance
def test_tampered_migration_detected_after_explicit_repair(tmp_path: Path) -> None:
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    _copy_migs(mig_dir)
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn, mig_dir)
    conn.execute("UPDATE schema_migrations SET checksum = NULL WHERE version = 2")
    conn.commit()
    conn.close()

    migrations = discover_migrations(mig_dir)
    conn2 = connect(path, key)
    repair_missing_checksums(conn2, migrations)
    validate_applied_migrations(conn2, migrations)
    conn2.close()

    target = next(mig_dir.glob("0002_*.sql"))
    target.write_bytes(target.read_bytes() + b"\n-- tampered-after-repair\n")

    conn3 = connect(path, key)
    with pytest.raises(DatabaseError, match="checksum mismatch"):
        apply_pending_migrations(conn3, mig_dir)
    conn3.close()
