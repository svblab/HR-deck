"""Интеграция: миграции на непустой БД без потери данных (TESTING §2.7 / §4)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import connect, create_database, generate_master_key, table_columns
from data.migrations import (
    apply_pending_migrations,
    current_version,
    default_migrations_dir,
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
    "status_history_corrections",
    "technical_events",
    "user_action_log",
    "report_templates",
    "report_template_versions",
    "template_generated_reports",
    "app_settings",
    "recovery_codes",
    "transport_installation",
    "transport_local_signing_keys",
    "transport_local_bootstrap_keys",
    "transport_peer_trust",
    "transport_direction_state",
    "transport_wk_keys",
    "transport_package_records",
    "import_sessions",
    "import_session_rows",
}

IMPORT_CONVERSION_TABLES = {
    "import_sessions",
    "import_session_rows",
}

_IMPORT_SESSION_COLUMNS = {
    "id",
    "file_content_hash",
    "last_accessed_at",
}

_IMPORT_SESSION_ROW_COLUMNS = {
    "id",
    "session_id",
    "source_row_number",
    "values_json",
}

_NOW = "2026-09-25T12:00:00Z"


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target

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
    assert statuses is not None and statuses[0] == 6
    inactive = conn.execute(
        "SELECT id FROM availability_statuses WHERE code = 'inactive'"
    ).fetchone()
    assert inactive is None
    employment_types = conn.execute(
        "SELECT code, archives_record FROM employment_types ORDER BY code"
    ).fetchall()
    assert dict(employment_types) == {
        "contractor": 0,
        "dismissed": 1,
        "staff": 0,
        "temporary": 0,
    }
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


@pytest.mark.acceptance
def test_migration_0018_import_conversion_sessions_on_nonempty_db(tmp_path: Path) -> None:
    """ADR-0012: migration 0018 applies on a seeded DB and creates staging tables."""
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v17 = _migrations_through(17, tmp_path)
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v17) == list(range(1, 18))
    ids = seed_synthetic_org(conn)
    emp_name = conn.execute(
        "SELECT full_name FROM employees WHERE id = ?", (ids["employee_a_id"],)
    ).fetchone()[0]
    conn.close()

    mig_v18 = _migrations_through(18, tmp_path / "v18apply")
    conn2 = connect(path, key)
    applied = apply_pending_migrations(conn2, migrations_dir=mig_v18)
    assert applied == [18]
    assert current_version(conn2) == 18

    tables = {
        r[0]
        for r in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    assert IMPORT_CONVERSION_TABLES <= tables
    assert table_columns(conn2, "import_sessions") == _IMPORT_SESSION_COLUMNS
    assert table_columns(conn2, "import_session_rows") == _IMPORT_SESSION_ROW_COLUMNS
    assert conn2.execute(
        "SELECT full_name FROM employees WHERE id = ?", (ids["employee_a_id"],)
    ).fetchone()[0] == emp_name

    index_row = conn2.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'index' AND tbl_name = 'import_sessions'"
        " AND name = 'idx_import_sessions_last_accessed_at'"
    ).fetchone()
    assert index_row is not None

    conn2.close()


@pytest.mark.acceptance
def test_migration_0018_import_conversion_constraints(tmp_path: Path) -> None:
    """ADR-0012: uniqueness, FK, and ON DELETE CASCADE on import conversion tables."""
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    assert current_version(conn) == expected_migration_versions()[-1]

    conn.execute(
        "INSERT INTO import_sessions (file_content_hash, last_accessed_at)"
        " VALUES (?, ?)",
        ("abc123", _NOW),
    )
    session_id = conn.execute("SELECT id FROM import_sessions").fetchone()[0]
    conn.execute(
        "INSERT INTO import_session_rows (session_id, source_row_number, values_json)"
        " VALUES (?, ?, ?)",
        (session_id, 2, "{}"),
    )
    conn.commit()

    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO import_sessions (file_content_hash, last_accessed_at)"
            " VALUES (?, ?)",
            ("abc123", _NOW),
        )

    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO import_session_rows (session_id, source_row_number, values_json)"
            " VALUES (?, ?, ?)",
            (session_id, 2, "{}"),
        )

    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO import_session_rows (session_id, source_row_number, values_json)"
            " VALUES (?, ?, ?)",
            (999, 3, "{}"),
        )

    conn.execute("DELETE FROM import_sessions WHERE id = ?", (session_id,))
    conn.commit()
    remaining = conn.execute("SELECT COUNT(*) FROM import_session_rows").fetchone()[0]
    assert remaining == 0
    conn.close()
