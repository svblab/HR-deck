"""Migration 0019: transport generation columns on nonempty DB."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from data.db import connect, create_database, generate_master_key, table_columns
from data.migrations import apply_pending_migrations, current_version, default_migrations_dir
from tests.fixtures.synthetic import seed_synthetic_org


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target


@pytest.mark.acceptance
def test_migration_0019_on_nonempty_db(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v18 = _migrations_through(18, tmp_path)
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v18) == list(range(1, 19))
    ids = seed_synthetic_org(conn)
    emp_name = conn.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0]
    conn.close()

    conn2 = connect(path, key)
    applied = apply_pending_migrations(conn2)
    assert applied == [19]
    assert current_version(conn2) == 19
    assert "generation" in table_columns(conn2, "transport_direction_state")
    assert "generation" in table_columns(conn2, "transport_package_records")
    gen = conn2.execute(
        "SELECT generation FROM transport_direction_state LIMIT 1"
    ).fetchone()
    if gen is not None:
        assert int(gen[0]) == 0
    assert conn2.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0] == emp_name
    conn2.close()
