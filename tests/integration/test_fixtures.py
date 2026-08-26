"""Проверки синтетических фикстур: одинаковое ФИО, разные ID, FK-целостность."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from tests.fixtures.synthetic import seed_synthetic_org


@pytest.mark.acceptance
def test_synthetic_two_employees_same_fio_different_ids(tmp_path: Path) -> None:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    ids = seed_synthetic_org(conn)

    assert ids["employee_a_id"] != ids["employee_b_id"]
    rows = conn.execute(
        "SELECT id, full_name FROM employees ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] == rows[1][1] == "Иванов Иван Иванович"
    assert {rows[0][0], rows[1][0]} == {ids["employee_a_id"], ids["employee_b_id"]}
    conn.close()


@pytest.mark.acceptance
def test_synthetic_referential_integrity(tmp_path: Path) -> None:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    seed_synthetic_org(conn)

    orphans = conn.execute(
        "SELECT e.id FROM employees e "
        "LEFT JOIN departments d ON d.id = e.department_id AND d.branch_id = e.branch_id "
        "WHERE d.id IS NULL"
    ).fetchall()
    assert orphans == []

    bad_div = conn.execute(
        "SELECT e.id FROM employees e "
        "JOIN divisions v ON v.id = e.division_id "
        "WHERE v.department_id != e.department_id"
    ).fetchall()
    assert bad_div == []

    dangling = conn.execute(
        "SELECT e.id FROM employees e "
        "LEFT JOIN positions p ON p.id = e.position_id "
        "LEFT JOIN employment_types t ON t.id = e.employment_type_id "
        "WHERE p.id IS NULL OR t.id IS NULL"
    ).fetchall()
    assert dangling == []
    conn.close()
