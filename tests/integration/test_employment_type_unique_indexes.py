"""E1-08: employment_types rebuild + partial unique indexes (ADR-0010 §4)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import connect, create_database, generate_master_key
from data.migrations import apply_pending_migrations, default_migrations_dir
from data.sql_script import execute_script_transactional

_OWNER_SCHEMA_SUFFIX = "_employment_type_owner_schema.sql"
_NOW = "2026-08-01T10:00:00Z"


def _owner_schema_migration() -> Path:
    matches = sorted(
        p for p in default_migrations_dir().glob("*.sql") if p.name.endswith(_OWNER_SCHEMA_SUFFIX)
    )
    assert len(matches) == 1, f"expected one {_OWNER_SCHEMA_SUFFIX}, found {matches}"
    return matches[0]


def _copy_migrations(names: list[str], root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    src = default_migrations_dir()
    for name in names:
        shutil.copy(src / name, target / name)
    return target


def _migration_name_lists() -> tuple[list[str], list[str]]:
    owner = _owner_schema_migration()
    all_names = [p.name for p in sorted(default_migrations_dir().glob("*.sql"))]
    before = [n for n in all_names if n < owner.name]
    return before, all_names


def _full_migrations_dir(tmp_path: Path) -> Path:
    _before, all_names = _migration_name_lists()
    return _copy_migrations(all_names, tmp_path / "full")


def _baseline_migrations_dir(tmp_path: Path) -> Path:
    before, _all_names = _migration_name_lists()
    return _copy_migrations(before, tmp_path / "before")


def _baseline_and_full_dirs(tmp_path: Path) -> tuple[Path, Path]:
    before, all_names = _migration_name_lists()
    return (
        _copy_migrations(before, tmp_path / "before"),
        _copy_migrations(all_names, tmp_path / "full"),
    )


def _norm_sql(sql: str) -> str:
    """Lower-case with whitespace collapsed for DDL comparisons."""
    return " ".join(sql.lower().split())


def _column_snapshot(
    conn: sqlcipher.Connection,
) -> dict[str, tuple[str, int, object]]:
    """name -> (type, notnull, dflt_value) from PRAGMA table_info."""
    out: dict[str, tuple[str, int, object]] = {}
    for row in conn.execute("PRAGMA table_info(employment_types)").fetchall():
        out[str(row[1])] = (str(row[2]), int(row[3]), row[4])
    return out


def _etype_id(conn: sqlcipher.Connection, code: str) -> int:
    row = conn.execute("SELECT id FROM employment_types WHERE code = ?", (code,)).fetchone()
    assert row is not None, f"missing employment type {code!r}"
    return int(row[0])


def _status_id(conn: sqlcipher.Connection, code: str) -> int:
    row = conn.execute("SELECT id FROM availability_statuses WHERE code = ?", (code,)).fetchone()
    assert row is not None, f"missing availability status {code!r}"
    return int(row[0])


def _seed_org_with_children(conn: sqlcipher.Connection) -> dict[str, int]:
    """employees + status_history referencing seeded staff / office."""
    staff_id = _etype_id(conn, "staff")
    office_id = _status_id(conn, "office")
    conn.execute(
        "INSERT INTO branches (external_id, name, is_archived, created_at, updated_at)"
        " VALUES ('br-north', 'Филиал Север', 0, ?, ?)",
        (_NOW, _NOW),
    )
    branch_id = int(
        conn.execute("SELECT id FROM branches WHERE external_id = 'br-north'").fetchone()[0]
    )
    conn.execute(
        "INSERT INTO departments"
        " (external_id, branch_id, name, is_archived, created_at, updated_at)"
        " VALUES ('dep-1', ?, 'Департамент', 0, ?, ?)",
        (branch_id, _NOW, _NOW),
    )
    dep_id = int(
        conn.execute("SELECT id FROM departments WHERE external_id = 'dep-1'").fetchone()[0]
    )
    conn.execute(
        "INSERT INTO divisions"
        " (external_id, branch_id, department_id, name, is_archived, created_at, updated_at)"
        " VALUES ('div-1', ?, ?, 'Отдел', 0, ?, ?)",
        (branch_id, dep_id, _NOW, _NOW),
    )
    div_id = int(conn.execute("SELECT id FROM divisions WHERE external_id = 'div-1'").fetchone()[0])
    conn.execute(
        "INSERT INTO positions"
        " (external_id, branch_id, name, is_archived, created_at, updated_at)"
        " VALUES ('pos-1', ?, 'Инженер', 0, ?, ?)",
        (branch_id, _NOW, _NOW),
    )
    pos_id = int(conn.execute("SELECT id FROM positions WHERE external_id = 'pos-1'").fetchone()[0])
    conn.execute(
        "INSERT INTO employees ("
        " external_id, full_name, position_id, branch_id, department_id, division_id,"
        " employment_type_id, note, hire_date, contacts, home_address,"
        " social_insurance_number, is_archived, created_at, updated_at"
        ") VALUES ('emp-a', 'Тестов Тест', ?, ?, ?, ?, ?, 'note', '2024-01-01',"
        " '+7-900-000-00-01', 'addr', '000-000-000 01', 0, ?, ?)",
        (pos_id, branch_id, dep_id, div_id, staff_id, _NOW, _NOW),
    )
    emp_id = int(conn.execute("SELECT id FROM employees WHERE external_id = 'emp-a'").fetchone()[0])
    conn.execute(
        "INSERT INTO status_history ("
        " employee_id, status_id, start_date, end_date, note, created_at"
        ") VALUES (?, ?, '2024-02-01', NULL, 'office day', ?)",
        (emp_id, office_id, _NOW),
    )
    hist_id = int(
        conn.execute(
            "SELECT id FROM status_history WHERE employee_id = ? AND status_id = ?",
            (emp_id, office_id),
        ).fetchone()[0]
    )
    conn.commit()
    return {
        "staff_id": staff_id,
        "office_id": office_id,
        "branch_id": branch_id,
        "emp_id": emp_id,
        "hist_id": hist_id,
    }


def test_migration_preserves_child_foreign_keys(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_before, mig_full = _baseline_and_full_dirs(tmp_path)
    conn = create_database(path, key)
    apply_pending_migrations(conn, migrations_dir=mig_before)
    ids = _seed_org_with_children(conn)
    conn.close()

    conn2 = connect(path, key)
    apply_pending_migrations(conn2, migrations_dir=mig_full)
    assert int(conn2.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    assert conn2.execute("PRAGMA foreign_key_check").fetchall() == []

    emp = conn2.execute(
        "SELECT e.id, et.code FROM employees e"
        " JOIN employment_types et ON et.id = e.employment_type_id"
        " WHERE e.id = ?",
        (ids["emp_id"],),
    ).fetchone()
    assert emp is not None
    assert int(emp[0]) == ids["emp_id"]
    assert str(emp[1]) == "staff"
    assert (
        int(
            conn2.execute(
                "SELECT employment_type_id FROM employees WHERE id = ?", (ids["emp_id"],)
            ).fetchone()[0]
        )
        == ids["staff_id"]
    )

    hist = conn2.execute(
        "SELECT sh.id, s.code FROM status_history sh"
        " JOIN availability_statuses s ON s.id = sh.status_id"
        " WHERE sh.id = ?",
        (ids["hist_id"],),
    ).fetchone()
    assert hist is not None
    assert int(hist[0]) == ids["hist_id"]
    assert str(hist[1]) == "office"
    assert (
        int(
            conn2.execute(
                "SELECT status_id FROM status_history WHERE id = ?", (ids["hist_id"],)
            ).fetchone()[0]
        )
        == ids["office_id"]
    )
    conn2.close()


# Model of the rebuild steps; does not execute the 0022 migration file.
def test_rebuild_pattern_fails_when_parent_row_is_lost(tmp_path: Path) -> None:
    """Copy of rebuild steps without re-inserting one parent row → IntegrityError on COMMIT.

    Models apply_pending_migrations: isolation_level=None, BEGIN, statements, COMMIT,
    with PRAGMA foreign_keys=ON on the connection (data.db connect/create_database).
    """
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_before = _baseline_migrations_dir(tmp_path)
    conn = create_database(path, key)
    apply_pending_migrations(conn, migrations_dir=mig_before)
    ids = _seed_org_with_children(conn)
    lost_id = ids["staff_id"]

    broken_sql = f"""
PRAGMA defer_foreign_keys=ON;
CREATE TEMP TABLE _employment_types_backup AS SELECT * FROM employment_types;
DROP TABLE employment_types;
CREATE TABLE employment_types (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archives_record INTEGER NOT NULL DEFAULT 0 CHECK (archives_record IN (0, 1)),
    owner_branch_id INTEGER NULL REFERENCES branches(id),
    sort_order INTEGER NOT NULL DEFAULT 0
);
INSERT INTO employment_types (
    id, code, name, is_archived, created_at, updated_at,
    owner_branch_id, archives_record, sort_order
)
SELECT
    id, code, name, is_archived, created_at, updated_at,
    NULL, archives_record, 0
FROM _employment_types_backup
WHERE id != {lost_id};
CREATE UNIQUE INDEX idx_employment_types_system_code
    ON employment_types(code) WHERE owner_branch_id IS NULL;
CREATE UNIQUE INDEX idx_employment_types_owner_code
    ON employment_types(owner_branch_id, code) WHERE owner_branch_id IS NOT NULL;
DROP TABLE _employment_types_backup;
"""
    assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    previous_isolation = conn.isolation_level
    conn.isolation_level = None
    conn.execute("BEGIN")
    try:
        execute_script_transactional(conn, broken_sql)
        with pytest.raises(sqlcipher.IntegrityError, match="FOREIGN KEY"):
            conn.execute("COMMIT")
    finally:
        try:
            conn.execute("ROLLBACK")
        except sqlcipher.Error:
            pass
        conn.isolation_level = previous_isolation
    conn.close()


def test_rebuild_preserves_check_and_defaults(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_before, mig_full = _baseline_and_full_dirs(tmp_path)

    conn = create_database(path, key)
    apply_pending_migrations(conn, migrations_dir=mig_before)
    before_cols = _column_snapshot(conn)
    conn.close()

    conn2 = connect(path, key)
    apply_pending_migrations(conn2, migrations_dir=mig_full)
    after_cols = _column_snapshot(conn2)

    for name, meta in before_cols.items():
        assert name in after_cols
        assert after_cols[name] == meta
    new_names = set(after_cols) - set(before_cols)
    assert new_names == {"owner_branch_id", "sort_order"}

    assert str(after_cols["is_archived"][2]) == "0"
    assert int(after_cols["is_archived"][1]) == 1
    assert str(after_cols["archives_record"][2]) == "0"
    assert int(after_cols["archives_record"][1]) == 1
    assert str(after_cols["sort_order"][2]) == "0"
    assert int(after_cols["sort_order"][1]) == 1
    assert int(after_cols["owner_branch_id"][1]) == 0

    with pytest.raises(sqlcipher.IntegrityError):
        conn2.execute(
            "INSERT INTO employment_types"
            " (code, name, archives_record, is_archived, created_at, updated_at)"
            " VALUES ('chk_arch', 'Bad archived', 0, 2, ?, ?)",
            (_NOW, _NOW),
        )
    conn2.rollback()

    with pytest.raises(sqlcipher.IntegrityError):
        conn2.execute(
            "INSERT INTO employment_types"
            " (code, name, archives_record, is_archived, created_at, updated_at)"
            " VALUES ('chk_rec', 'Bad archives_record', 2, 0, ?, ?)",
            (_NOW, _NOW),
        )
    conn2.rollback()

    # DEFAULT 0 behaviour for new insert omitting the flag columns
    conn2.execute(
        "INSERT INTO employment_types (code, name, created_at, updated_at)"
        " VALUES ('chk_defaults', 'Check Defaults', ?, ?)",
        (_NOW, _NOW),
    )
    row = conn2.execute(
        "SELECT is_archived, archives_record, sort_order, owner_branch_id"
        " FROM employment_types WHERE code = 'chk_defaults'"
    ).fetchone()
    assert row is not None
    assert int(row[0]) == 0
    assert int(row[1]) == 0
    assert int(row[2]) == 0
    assert row[3] is None
    conn2.close()


def test_two_branches_same_additional_code(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_full = _full_migrations_dir(tmp_path)
    conn = create_database(path, key)
    apply_pending_migrations(conn, migrations_dir=mig_full)

    conn.execute(
        "INSERT INTO branches (external_id, name, is_archived, created_at, updated_at)"
        " VALUES ('br-a', 'A', 0, ?, ?), ('br-b', 'B', 0, ?, ?)",
        (_NOW, _NOW, _NOW, _NOW),
    )
    a_id = int(conn.execute("SELECT id FROM branches WHERE external_id = 'br-a'").fetchone()[0])
    b_id = int(conn.execute("SELECT id FROM branches WHERE external_id = 'br-b'").fetchone()[0])
    conn.execute(
        "INSERT INTO employment_types"
        " (code, name, archives_record, is_archived, created_at, updated_at, owner_branch_id)"
        " VALUES ('addon', 'Addon A', 0, 0, ?, ?, ?)",
        (_NOW, _NOW, a_id),
    )
    conn.execute(
        "INSERT INTO employment_types"
        " (code, name, archives_record, is_archived, created_at, updated_at, owner_branch_id)"
        " VALUES ('addon', 'Addon B', 0, 0, ?, ?, ?)",
        (_NOW, _NOW, b_id),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT owner_branch_id, name FROM employment_types"
        " WHERE code = 'addon' ORDER BY owner_branch_id"
    ).fetchall()
    assert len(rows) == 2
    assert {int(r[0]) for r in rows} == {a_id, b_id}
    conn.close()


def test_same_branch_same_additional_code_rejected(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_full = _full_migrations_dir(tmp_path)
    conn = create_database(path, key)
    apply_pending_migrations(conn, migrations_dir=mig_full)

    index_sql = {
        str(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT name, sql FROM sqlite_master"
            " WHERE type = 'index' AND name IN ("
            "  'idx_employment_types_system_code',"
            "  'idx_employment_types_owner_code'"
            ")"
        ).fetchall()
    }
    assert "idx_employment_types_system_code" in index_sql
    assert "idx_employment_types_owner_code" in index_sql
    system_norm = _norm_sql(index_sql["idx_employment_types_system_code"])
    owner_norm = _norm_sql(index_sql["idx_employment_types_owner_code"])
    assert "where owner_branch_id is null" in system_norm
    assert "where owner_branch_id is not null" in owner_norm

    conn.execute(
        "INSERT INTO branches (external_id, name, is_archived, created_at, updated_at)"
        " VALUES ('br-dup', 'Dup', 0, ?, ?)",
        (_NOW, _NOW),
    )
    branch_id = int(
        conn.execute("SELECT id FROM branches WHERE external_id = 'br-dup'").fetchone()[0]
    )
    conn.execute(
        "INSERT INTO employment_types"
        " (code, name, archives_record, is_archived, created_at, updated_at, owner_branch_id)"
        " VALUES ('addon', 'Addon 1', 0, 0, ?, ?, ?)",
        (_NOW, _NOW, branch_id),
    )
    conn.commit()
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO employment_types"
            " (code, name, archives_record, is_archived, created_at, updated_at,"
            "  owner_branch_id)"
            " VALUES ('addon', 'Addon 2', 0, 0, ?, ?, ?)",
            (_NOW, _NOW, branch_id),
        )
    conn.rollback()
    conn.close()


def test_base_codes_remain_globally_unique(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_full = _full_migrations_dir(tmp_path)
    conn = create_database(path, key)
    apply_pending_migrations(conn, migrations_dir=mig_full)

    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO employment_types"
            " (code, name, archives_record, is_archived, created_at, updated_at,"
            "  owner_branch_id)"
            " VALUES ('staff', 'Dup Staff', 0, 0, ?, ?, NULL)",
            (_NOW, _NOW),
        )
    conn.rollback()
    conn.close()
