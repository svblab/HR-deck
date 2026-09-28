"""Режим демо: seed и повторный вход без затрагивания рабочей БД."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.demo import (
    DEMO_COMPANY_NAME,
    DEMO_EMPLOYEE_COUNT,
    DEMO_LOGIN,
    DEMO_PASSWORD,
    prepare_demo_database,
    seed_demo_org,
)


@pytest.mark.acceptance
def test_prepare_demo_database_creates_admin_and_employees(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    conn, session = prepare_demo_database(db, force_reset=True)
    try:
        assert session.login == DEMO_LOGIN
        assert session.inactivity_timeout_enabled is False
        count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        assert count == DEMO_EMPLOYEE_COUNT
        hist = conn.execute("SELECT COUNT(*) FROM status_history").fetchone()[0]
        assert hist >= DEMO_EMPLOYEE_COUNT  # one+ per employee

        # смесь статусов (не только «в офисе»)
        status_ids = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT status_id FROM status_history"
            ).fetchall()
        }
        assert len(status_ids) >= 4

        # компания
        from data.accounts import SettingsRepository

        name = SettingsRepository(conn).get("company_name", "") or ""
        assert name == DEMO_COMPANY_NAME

        # повторный вызов с force_reset пересоздаёт
        conn.close()
        conn2, session2 = prepare_demo_database(db, force_reset=True)
        try:
            count2 = conn2.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
            assert count2 == DEMO_EMPLOYEE_COUNT
            assert session2.login == DEMO_LOGIN
            # пароль всё ещё demo (косвенно через успешный login внутри prepare)
            assert DEMO_PASSWORD == "demo"
        finally:
            conn2.close()
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


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
def test_demo_db_path_isolated_from_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from data.paths import default_db_path
    from services.demo import demo_db_path

    monkeypatch.setenv("PERSONNEL_AVAILABILITY_DATA", str(tmp_path / "workdir"))
    work = default_db_path()
    demo = demo_db_path()
    assert work != demo
    assert "personnel-availability-demo" in str(demo)
