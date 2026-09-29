"""Режим демо: seed, сброс и повторный вход без затрагивания рабочей БД."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from services.demo import (
    DEMO_COMPANY_NAME,
    DEMO_EMPLOYEE_COUNT,
    DEMO_LOGIN,
    launch_demo_database,
    prepare_demo_database,
    seed_demo_org,
)


def _utc_today() -> str:
    return datetime.now(UTC).date().isoformat()


@pytest.mark.acceptance
def test_prepare_demo_database_seeds_org_statuses_and_idle_off(tmp_path: Path) -> None:
    from data.accounts import SettingsRepository

    db = tmp_path / "demo.db"
    conn, session = prepare_demo_database(db, force_reset=True)
    try:
        assert session.login == DEMO_LOGIN
        assert session.inactivity_timeout_enabled is False
        assert session.inactivity_timeout_seconds == 0
        settings = SettingsRepository(conn)
        assert settings.get("company_name") == DEMO_COMPANY_NAME
        assert settings.get("inactivity_timeout_enabled") == "0"
        count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        assert count == DEMO_EMPLOYEE_COUNT
        hist = conn.execute("SELECT COUNT(*) FROM status_history").fetchone()[0]
        assert hist == DEMO_EMPLOYEE_COUNT + 1
        status_ids = {
            row[0]
            for row in conn.execute("SELECT DISTINCT status_id FROM status_history")
        }
        assert status_ids == {1, 2, 3, 4, 5, 6}
        today = _utc_today()
        expired = {
            row[0]
            for row in conn.execute(
                "SELECT employee_id FROM status_history "
                "WHERE end_date IS NOT NULL AND end_date < ?",
                (today,),
            )
        }
        assert expired == {12, 14, 15}
        future = conn.execute(
            "SELECT 1 FROM status_history "
            "WHERE employee_id = 1 AND status_id = 5 AND start_date > ?",
            (today,),
        ).fetchone()
        assert future is not None
    finally:
        conn.close()


@pytest.mark.acceptance
def test_force_reset_discards_manual_edits(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    conn, _session = prepare_demo_database(db, force_reset=True)
    conn.execute("UPDATE employees SET full_name = ? WHERE id = 1", ("Изменённый",))
    conn.commit()
    conn.close()
    conn2, session2 = prepare_demo_database(db, force_reset=True)
    try:
        name = conn2.execute("SELECT full_name FROM employees WHERE id = 1").fetchone()[0]
        assert name == "Иванов Иван Иванович"
        assert session2.login == DEMO_LOGIN
        count = conn2.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        assert count == DEMO_EMPLOYEE_COUNT
    finally:
        conn2.close()


@pytest.mark.acceptance
def test_existing_demo_database_logs_in_and_keeps_idle_off(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    conn, _session = prepare_demo_database(db, force_reset=True)
    conn.close()
    conn2, session2 = prepare_demo_database(db, force_reset=False)
    try:
        assert session2.login == DEMO_LOGIN
        assert session2.inactivity_timeout_enabled is False
        assert session2.inactivity_timeout_seconds == 0
        count = conn2.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        assert count == DEMO_EMPLOYEE_COUNT
    finally:
        conn2.close()


@pytest.mark.acceptance
def test_launch_demo_database_replaces_corrupt_file(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    db.write_bytes(b"broken")
    conn, session = launch_demo_database(db)
    try:
        assert session.login == DEMO_LOGIN
        assert session.inactivity_timeout_enabled is False
        count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        assert count == DEMO_EMPLOYEE_COUNT
        assert db.is_file()
        assert db.stat().st_size >= 512
    finally:
        conn.close()


@pytest.mark.acceptance
def test_seed_demo_org_referential_integrity(tmp_path: Path) -> None:
    from data.db import create_database, generate_master_key
    from data.migrations import apply_pending_migrations

    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    ids = seed_demo_org(conn)
    assert ids["employee_count"] == DEMO_EMPLOYEE_COUNT
    orphans = conn.execute(
        "SELECT e.id FROM employees e "
        "LEFT JOIN branches b ON b.id = e.branch_id "
        "WHERE b.id IS NULL"
    ).fetchall()
    assert orphans == []
    conn.close()


@pytest.mark.acceptance
def test_demo_db_path_isolated_from_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data.paths import default_db_path
    from services.demo import demo_db_path

    monkeypatch.setenv("PERSONNEL_AVAILABILITY_DATA", str(tmp_path / "workdir"))
    work = default_db_path()
    demo = demo_db_path()
    assert work != demo
    assert "personnel-availability-demo" in str(demo)
