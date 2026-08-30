"""FK: orphan rows невозможны при PRAGMA foreign_keys=ON (P1-3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from tests.fixtures.synthetic import seed_synthetic_org

_NOW = "2026-08-01T10:00:00Z"


@pytest.fixture()
def conn(tmp_path: Path):
    key = generate_master_key()
    c = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(c)
    seed_synthetic_org(c)
    yield c
    c.close()


@pytest.mark.acceptance
def test_employees_fk_position(conn) -> None:
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO employees ("
            " full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, is_archived, created_at, updated_at"
            ") VALUES ('X', 999, 1, 1, 1, 1, 0, ?, ?)",
            (_NOW, _NOW),
        )


@pytest.mark.acceptance
def test_employees_fk_employment_type(conn) -> None:
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO employees ("
            " full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, is_archived, created_at, updated_at"
            ") VALUES ('X', 1, 1, 1, 1, 999, 0, ?, ?)",
            (_NOW, _NOW),
        )


@pytest.mark.acceptance
def test_employees_fk_branch_via_department_parent(conn) -> None:
    """Филиал как FK: департамент не может ссылаться на несуществующий branch."""
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO departments ("
            " id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (99, 999, 'x', 0, ?, ?)",
            (_NOW, _NOW),
        )


@pytest.mark.acceptance
def test_employees_fk_department_via_missing_dept(conn) -> None:
    """Несуществующий department_id → FK (или org-trigger); orphan не создаётся."""
    before = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    with pytest.raises((sqlcipher.IntegrityError, sqlcipher.DatabaseError)):
        conn.execute(
            "INSERT INTO employees ("
            " full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, is_archived, created_at, updated_at"
            ") VALUES ('X', 1, 1, 999, NULL, 1, 0, ?, ?)",
            (_NOW, _NOW),
        )
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before


@pytest.mark.acceptance
def test_employees_fk_division_via_missing_division(conn) -> None:
    before = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    with pytest.raises((sqlcipher.IntegrityError, sqlcipher.DatabaseError)):
        conn.execute(
            "INSERT INTO employees ("
            " full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, is_archived, created_at, updated_at"
            ") VALUES ('X', 1, 1, 1, 999, 1, 0, ?, ?)",
            (_NOW, _NOW),
        )
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before


@pytest.mark.acceptance
def test_divisions_fk_department(conn) -> None:
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO divisions ("
            " id, department_id, name, is_archived, created_at, updated_at"
            ") VALUES (99, 999, 'x', 0, ?, ?)",
            (_NOW, _NOW),
        )


@pytest.mark.acceptance
def test_status_history_fk_to_employee_and_status(conn) -> None:
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO status_history ("
            " employee_id, status_id, start_date, created_at"
            ") VALUES (999, 1, '2026-08-01', ?)",
            (_NOW,),
        )
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO status_history ("
            " employee_id, status_id, start_date, created_at"
            ") VALUES (1, 999, '2026-08-01', ?)",
            (_NOW,),
        )


@pytest.mark.acceptance
def test_accounts_fk_to_roles(conn) -> None:
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO accounts ("
            " login, password_hash, password_salt, role_id, is_active,"
            " created_at, updated_at"
            ") VALUES ('u', 'h', 's', 999, 1, ?, ?)",
            (_NOW, _NOW),
        )


@pytest.mark.acceptance
def test_template_generated_reports_fk(conn) -> None:
    now = "2026-08-01T10:00:00Z"
    conn.execute(
        "INSERT INTO report_templates (name, format, is_archived, created_at, updated_at)"
        " VALUES ('t', 'excel', 0, ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO report_template_versions ("
        " template_id, version_number, stored_path, created_at"
        ") VALUES (1, 1, '/tmp/x', ?)",
        (now,),
    )
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO template_generated_reports ("
            " template_version_id, output_path, generated_at"
            ") VALUES (999, '/out', ?)",
            (now,),
        )


@pytest.mark.acceptance
def test_report_template_versions_fk(conn) -> None:
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "INSERT INTO report_template_versions ("
            " template_id, version_number, stored_path, created_at"
            ") VALUES (999, 1, '/tmp/x', ?)",
            (_NOW,),
        )
