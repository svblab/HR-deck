"""Режим демо: seed и повторный вход без затрагивания рабочей БД."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.demo import (
    DEMO_LOGIN,
    DEMO_PASSWORD,
    prepare_demo_database,
    seed_demo_org,
)


@pytest.mark.acceptance
def test_prepare_demo_database_creates_admin_and_employees(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    conn, session = prepare_demo_database(db)
    try:
        assert session.login == DEMO_LOGIN
        count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        assert count >= 15
        hist = conn.execute("SELECT COUNT(*) FROM status_history").fetchone()[0]
        assert hist >= 10
        # повторный вызов не дублирует сотрудников
        conn.close()
        conn2, session2 = prepare_demo_database(db)
        try:
            count2 = conn2.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
            assert count2 == count
            assert session2.login == DEMO_LOGIN
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
    assert ids["employee_count"] >= 15
    orphans = conn.execute(
        "SELECT e.id FROM employees e "
        "LEFT JOIN branches b ON b.id = e.branch_id "
        "WHERE b.id IS NULL"
    ).fetchall()
    assert orphans == []
    conn.close()
