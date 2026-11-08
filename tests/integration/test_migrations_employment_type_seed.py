"""Integration: E1-01 seed transferred/erroneous + contract abort (ADR-0011 §1.1)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import connect, create_database, generate_master_key
from data.migrations import (
    apply_pending_migrations,
    current_version,
    default_migrations_dir,
    expected_migration_versions,
)

_CONTRACT = {
    "transferred": ("Переведён", 1, 0),
    "erroneous": ("Ошибочная запись", 1, 0),
}
_NOW = "1970-01-01T00:00:00Z"


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target


def _row(conn: sqlcipher.Connection, code: str) -> tuple[str, int, int] | None:
    found = conn.execute(
        "SELECT name, archives_record, is_archived FROM employment_types WHERE code = ?",
        (code,),
    ).fetchone()
    if found is None:
        return None
    return (str(found[0]), int(found[1]), int(found[2]))


def _insert_employment_type(
    conn: sqlcipher.Connection,
    *,
    code: str,
    name: str,
    archives_record: int,
    is_archived: int,
) -> None:
    conn.execute(
        "INSERT INTO employment_types"
        " (code, name, archives_record, is_archived, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (code, name, archives_record, is_archived, _NOW, _NOW),
    )
    conn.commit()


@pytest.mark.acceptance
def test_transferred_and_erroneous_seeded_with_contract_flags(tmp_path: Path) -> None:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    applied = apply_pending_migrations(conn)
    assert applied == expected_migration_versions()
    assert current_version(conn) == applied[-1]
    for code, expected in _CONTRACT.items():
        assert _row(conn, code) == expected
    conn.close()


@pytest.mark.acceptance
def test_matching_existing_rows_are_skipped(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v19 = _migrations_through(19, tmp_path)
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v19) == list(range(1, 20))
    for code, (name, archives_record, is_archived) in _CONTRACT.items():
        _insert_employment_type(
            conn,
            code=code,
            name=name,
            archives_record=archives_record,
            is_archived=is_archived,
        )
    before = {
        code: conn.execute(
            "SELECT id, name, archives_record, is_archived, created_at, updated_at"
            " FROM employment_types WHERE code = ?",
            (code,),
        ).fetchone()
        for code in _CONTRACT
    }
    conn.close()

    conn2 = connect(path, key)
    mig_v20 = _migrations_through(20, tmp_path / "through20")
    applied = apply_pending_migrations(conn2, migrations_dir=mig_v20)
    assert applied == [20]
    assert current_version(conn2) == 20
    for code, row in before.items():
        after = conn2.execute(
            "SELECT id, name, archives_record, is_archived, created_at, updated_at"
            " FROM employment_types WHERE code = ?",
            (code,),
        ).fetchone()
        assert after == row
    conn2.close()


@pytest.mark.acceptance
def test_contract_mismatch_rolls_back_and_does_not_record_version(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v19 = _migrations_through(19, tmp_path)
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v19) == list(range(1, 20))
    _insert_employment_type(
        conn,
        code="transferred",
        name="Other name",
        archives_record=1,
        is_archived=0,
    )
    conn.close()

    conn2 = connect(path, key)
    with pytest.raises(sqlcipher.IntegrityError, match="employment type seed contract mismatch"):
        apply_pending_migrations(conn2)
    assert current_version(conn2) == 19
    versions = [
        int(row[0])
        for row in conn2.execute("SELECT version FROM schema_migrations ORDER BY version")
    ]
    assert 20 not in versions
    assert _row(conn2, "transferred") == ("Other name", 1, 0)
    assert _row(conn2, "erroneous") is None
    conn2.close()


@pytest.mark.acceptance
def test_flag_mismatch_rolls_back_whole_file(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v19 = _migrations_through(19, tmp_path)
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v19) == list(range(1, 20))
    _insert_employment_type(
        conn,
        code="erroneous",
        name="Ошибочная запись",
        archives_record=0,
        is_archived=0,
    )
    conn.close()

    conn2 = connect(path, key)
    with pytest.raises(sqlcipher.IntegrityError, match="employment type seed contract mismatch"):
        apply_pending_migrations(conn2)
    assert current_version(conn2) == 19
    assert _row(conn2, "erroneous") == ("Ошибочная запись", 0, 0)
    assert _row(conn2, "transferred") is None
    conn2.close()


@pytest.mark.acceptance
def test_is_archived_mismatch_rolls_back_whole_file(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v19 = _migrations_through(19, tmp_path)
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v19) == list(range(1, 20))
    _insert_employment_type(
        conn,
        code="transferred",
        name="Переведён",
        archives_record=1,
        is_archived=1,
    )
    conn.close()

    conn2 = connect(path, key)
    with pytest.raises(sqlcipher.IntegrityError, match="employment type seed contract mismatch"):
        apply_pending_migrations(conn2)
    assert current_version(conn2) == 19
    versions = [
        int(row[0])
        for row in conn2.execute("SELECT version FROM schema_migrations ORDER BY version")
    ]
    assert 20 not in versions
    assert _row(conn2, "transferred") == ("Переведён", 1, 1)
    assert _row(conn2, "erroneous") is None
    conn2.close()


@pytest.mark.acceptance
def test_one_matching_one_mismatching_code_aborts_whole_file(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v19 = _migrations_through(19, tmp_path)
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v19) == list(range(1, 20))
    _insert_employment_type(
        conn,
        code="transferred",
        name="Переведён",
        archives_record=1,
        is_archived=0,
    )
    _insert_employment_type(
        conn,
        code="erroneous",
        name="Ошибочная запись",
        archives_record=0,
        is_archived=0,
    )
    conn.close()

    conn2 = connect(path, key)
    with pytest.raises(sqlcipher.IntegrityError, match="employment type seed contract mismatch"):
        apply_pending_migrations(conn2)
    assert current_version(conn2) == 19
    versions = [
        int(row[0])
        for row in conn2.execute("SELECT version FROM schema_migrations ORDER BY version")
    ]
    assert 20 not in versions
    assert _row(conn2, "transferred") == ("Переведён", 1, 0)
    transferred_count = conn2.execute(
        "SELECT COUNT(*) FROM employment_types WHERE code = ?",
        ("transferred",),
    ).fetchone()
    assert transferred_count is not None and int(transferred_count[0]) == 1
    assert _row(conn2, "erroneous") == ("Ошибочная запись", 0, 0)
    conn2.close()
