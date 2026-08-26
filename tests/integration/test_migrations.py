"""Интеграция: миграции на непустой БД без потери данных (TESTING §2.7 / §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import connect, create_database, generate_master_key, table_columns
from data.migrations import (
    apply_pending_migrations,
    current_version,
    expected_migration_versions,
)
from tests.fixtures.synthetic import seed_synthetic_org

REQUIRED_TABLES = {
    "schema_migrations",
    "roles",
    "accounts",
    "branches",
    "departments",
    "divisions",
    "positions",
    "employment_types",
    "availability_statuses",
    "employees",
    "status_history",
    "technical_events",
    "user_action_log",
    "report_templates",
    "report_template_versions",
    "app_settings",
    "recovery_codes",
}

RESERVED_EMPLOYEE_COLUMNS = {
    "hire_date",
    "contacts",
    "home_address",
    "social_insurance_number",
}


@pytest.mark.acceptance
def test_initial_migration_creates_schema_and_seeds(tmp_path: Path) -> None:
    """ТЗ §3.1 / §5: схема с суррогатными ID и резервными полями; сиды справочников."""
    expected = expected_migration_versions()
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    applied = apply_pending_migrations(conn)
    assert applied == expected
    assert current_version(conn) == expected[-1]

    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert REQUIRED_TABLES <= tables
    assert RESERVED_EMPLOYEE_COLUMNS <= table_columns(conn, "employees")

    roles = conn.execute("SELECT code FROM roles ORDER BY id").fetchall()
    assert [r[0] for r in roles] == ["administrator", "hr_employee", "observer"]
    statuses = conn.execute("SELECT COUNT(*) FROM availability_statuses").fetchone()
    assert statuses is not None and statuses[0] == 7
    conn.close()


@pytest.mark.acceptance
def test_reapply_migrations_on_nonempty_preserves_data(tmp_path: Path) -> None:
    """Миграции на непустой БД: повторный прогон не теряет строки (TESTING §4)."""
    expected = expected_migration_versions()
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    assert apply_pending_migrations(conn) == expected
    ids = seed_synthetic_org(conn)
    conn.close()

    conn2 = connect(path, key)
    assert apply_pending_migrations(conn2) == []
    assert current_version(conn2) == expected[-1]
    row = conn2.execute(
        "SELECT full_name, social_insurance_number FROM employees WHERE id = ?",
        (ids["employee_a_id"],),
    ).fetchone()
    assert row is not None
    assert row[0] == "Иванов Иван Иванович"
    assert row[1] == "000-000-000 01"
    twin = conn2.execute(
        "SELECT COUNT(*) FROM employees WHERE full_name = ?",
        ("Иванов Иван Иванович",),
    ).fetchone()
    assert twin is not None and twin[0] == 2
    conn2.close()
