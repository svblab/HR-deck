"""E1-05: employees.transfer_target_branch_id column, FK, repository read/write."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import connect, create_database, generate_master_key
from data.employees import EmployeeRepository
from data.migrations import apply_pending_migrations, default_migrations_dir
from tests.fixtures.synthetic import seed_synthetic_org

_MIGRATION_NAME = "0021_employee_transfer_target_branch.sql"
_NOW = "2026-08-01T10:00:00Z"


def _migration_version() -> int:
    path = default_migrations_dir() / _MIGRATION_NAME
    assert path.is_file(), f"missing migration {path}"
    return int(_MIGRATION_NAME[:4])


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target


def _column_info(conn, name: str) -> tuple[object, ...] | None:
    for row in conn.execute("PRAGMA table_info(employees)").fetchall():
        if row[1] == name:
            return row
    return None


@pytest.fixture()
def migrated_conn(tmp_path: Path):
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn)
    seed_synthetic_org(conn)
    yield conn
    conn.close()


def test_migration_adds_nullable_fk_column(tmp_path: Path) -> None:
    version = _migration_version()
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_before = _migrations_through(version - 1, tmp_path / "before")
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_before) == list(
        range(1, version)
    )
    assert _column_info(conn, "transfer_target_branch_id") is None
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    conn.close()

    conn2 = connect(path, key)
    mig_at = _migrations_through(version, tmp_path / "at")
    applied = apply_pending_migrations(conn2, migrations_dir=mig_at)
    assert applied == [version]

    col = _column_info(conn2, "transfer_target_branch_id")
    assert col is not None
    assert col[2] == "INTEGER"
    assert int(col[3]) == 0  # not NOT NULL

    fks = conn2.execute("PRAGMA foreign_key_list(employees)").fetchall()
    assert any(
        row[2] == "branches" and row[3] == "transfer_target_branch_id" and row[4] == "id"
        for row in fks
    )

    nulls = conn2.execute(
        "SELECT transfer_target_branch_id FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert nulls is not None
    assert nulls[0] is None
    all_null = conn2.execute(
        "SELECT COUNT(*) FROM employees WHERE transfer_target_branch_id IS NOT NULL"
    ).fetchone()
    assert all_null is not None
    assert int(all_null[0]) == 0
    conn2.close()


def test_fk_enforced_on_insert_and_update(migrated_conn) -> None:
    conn = migrated_conn
    assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO employees ("
            " external_id, full_name, position_id, branch_id, department_id,"
            " employment_type_id, is_archived, created_at, updated_at,"
            " transfer_target_branch_id"
            ") VALUES (?, 'X', 1, 1, 1, 1, 0, ?, ?, 99999)",
            ("ext-fk-bad-ins", _NOW, _NOW),
        )
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "UPDATE employees SET transfer_target_branch_id = 99999 WHERE id = 1"
        )


def test_repository_reads_null_and_set_value(migrated_conn) -> None:
    conn = migrated_conn
    repo = EmployeeRepository(conn)
    record = repo.get(1)
    assert record is not None
    assert record.transfer_target_branch_id is None

    repo.set_transfer_target_branch_id(
        1, updated_at=_NOW, transfer_target_branch_id=1
    )
    after = repo.get(1)
    assert after is not None
    assert after.transfer_target_branch_id == 1


def test_existing_update_does_not_clear_transfer_target(migrated_conn) -> None:
    conn = migrated_conn
    repo = EmployeeRepository(conn)
    repo.set_transfer_target_branch_id(
        1, updated_at=_NOW, transfer_target_branch_id=1
    )
    before = repo.get(1)
    assert before is not None
    assert before.transfer_target_branch_id == 1

    repo.update(
        1,
        full_name=before.full_name,
        position_id=before.position_id,
        branch_id=before.branch_id,
        department_id=before.department_id,
        employment_type_id=before.employment_type_id,
        updated_at="2026-08-02T10:00:00Z",
        division_id=before.division_id,
        note=before.note,
    )
    after = repo.get(1)
    assert after is not None
    assert after.transfer_target_branch_id == 1
    assert after.updated_at == "2026-08-02T10:00:00Z"


def test_setter_none_clears_previous_value(migrated_conn) -> None:
    repo = EmployeeRepository(migrated_conn)
    repo.set_transfer_target_branch_id(1, updated_at=_NOW, transfer_target_branch_id=1)
    cleared_at = "2026-08-03T10:00:00Z"
    repo.set_transfer_target_branch_id(
        1, updated_at=cleared_at, transfer_target_branch_id=None
    )
    after = repo.get(1)
    assert after is not None
    assert after.transfer_target_branch_id is None
    assert after.updated_at == cleared_at


def test_fk_valid_insert_succeeds_invalid_raises(migrated_conn) -> None:
    conn = migrated_conn
    conn.execute(
        "INSERT INTO employees ("
        " external_id, full_name, position_id, branch_id, department_id,"
        " employment_type_id, is_archived, created_at, updated_at,"
        " transfer_target_branch_id"
        ") VALUES (?, 'Y', 1, 1, 1, 1, 0, ?, ?, 1)",
        ("ext-fk-ok-ins", _NOW, _NOW),
    )
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO employees ("
            " external_id, full_name, position_id, branch_id, department_id,"
            " employment_type_id, is_archived, created_at, updated_at,"
            " transfer_target_branch_id"
            ") VALUES (?, 'Z', 1, 1, 1, 1, 0, ?, ?, 99999)",
            ("ext-fk-bad-ins-2", _NOW, _NOW),
        )


def test_foreign_key_check_clean_after_migration(migrated_conn) -> None:
    rows = migrated_conn.execute("PRAGMA foreign_key_check").fetchall()
    assert rows == []
