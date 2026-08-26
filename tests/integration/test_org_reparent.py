"""Org reparent guards: нельзя двигать parent при существующих ссылках (P1-1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from tests.fixtures.synthetic import seed_synthetic_org

_NOW = "2026-08-01T10:00:00Z"


@pytest.mark.acceptance
def test_cannot_reparent_department_referenced_by_employees(tmp_path: Path) -> None:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    seed_synthetic_org(conn)
    conn.execute(
        "INSERT INTO branches (id, name, is_archived, created_at, updated_at) "
        "VALUES (2, 'Other', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.commit()
    with pytest.raises(sqlcipher.DatabaseError, match="cannot reparent department"):
        conn.execute("UPDATE departments SET branch_id = 2 WHERE id = 1")
    branch = conn.execute("SELECT branch_id FROM departments WHERE id = 1").fetchone()[0]
    assert branch == 1
    conn.close()


@pytest.mark.acceptance
def test_cannot_reparent_division_referenced_by_employees(tmp_path: Path) -> None:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    seed_synthetic_org(conn)
    conn.execute(
        "INSERT INTO departments (id, branch_id, name, is_archived, created_at, updated_at) "
        "VALUES (2, 1, 'Dept B', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.commit()
    with pytest.raises(sqlcipher.DatabaseError, match="cannot reparent division"):
        conn.execute("UPDATE divisions SET department_id = 2 WHERE id = 1")
    dept = conn.execute("SELECT department_id FROM divisions WHERE id = 1").fetchone()[0]
    assert dept == 1
    conn.close()


@pytest.mark.acceptance
def test_cannot_reparent_department_with_child_divisions(tmp_path: Path) -> None:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    # Филиал + департамент + отдел без сотрудников.
    conn.execute(
        "INSERT INTO branches (id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 'B1', 0, ?, ?), (2, 'B2', 0, ?, ?)",
        (_NOW, _NOW, _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO departments (id, branch_id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 1, 'D1', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO divisions (id, department_id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 1, 'V1', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.commit()
    with pytest.raises(sqlcipher.DatabaseError, match="child divisions"):
        conn.execute("UPDATE departments SET branch_id = 2 WHERE id = 1")
    conn.close()
