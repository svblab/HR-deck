"""Migration 0008: metadata columns + generated report linkage."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from data.db import connect, create_database, generate_master_key, table_columns
from data.migrations import apply_pending_migrations, current_version, default_migrations_dir
from tests.fixtures.synthetic import seed_synthetic_org


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir()
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target


@pytest.mark.acceptance
def test_migration_0008_on_nonempty_db(tmp_path: Path) -> None:
    """Миграция 0008 на непустой БД: новые колонки и таблица linkage."""
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v7 = _migrations_through(7, tmp_path)
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v7) == list(range(1, 8))
    ids = seed_synthetic_org(conn)
    now = "2026-08-30T10:00:00Z"
    conn.execute(
        "INSERT INTO report_templates (name, format, is_archived, created_at, updated_at)"
        " VALUES ('legacy', 'excel', 0, ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO report_template_versions ("
        " template_id, version_number, stored_path, created_at"
        ") VALUES (1, 1, '/tmp/legacy.xlsx', ?)",
        (now,),
    )
    conn.commit()
    emp_name = conn.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0]
    conn.close()

    conn2 = connect(path, key)
    applied = apply_pending_migrations(conn2)
    assert applied == [8]
    assert current_version(conn2) == 8
    version_cols = table_columns(conn2, "report_template_versions")
    assert {"contract_version", "binding_mode", "manifest_path"} <= version_cols
    row = conn2.execute(
        "SELECT contract_version, binding_mode FROM report_template_versions WHERE id=1"
    ).fetchone()
    assert row == ("1.0", "excel")
    tables = {
        r[0]
        for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "template_generated_reports" in tables
    assert conn2.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0] == emp_name
    conn2.close()
