"""Integration: контракт архива сотрудника и типов занятости (ADR-0011)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import Connection
from domain.employee import EmployeeUpdateInput
from domain.employment_types import DEFAULT_ARCHIVING_EMPLOYMENT_CODE
from services.bootstrap import BootstrapService
from services.directories import DirectoryError, DirectoryService
from services.employees import EmployeeService
from services.session import SessionState
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org

_CLOCK = "2026-09-20T10:00:00Z"


def _open_db(tmp_path: Path) -> tuple[Connection, SessionState]:
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: _CLOCK).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


def _employment_type_flags(conn: Connection) -> dict[str, tuple[bool, bool]]:
    rows = conn.execute(
        "SELECT code, archives_record, is_archived FROM employment_types ORDER BY code"
    ).fetchall()
    return {str(code): (bool(archives), bool(archived)) for code, archives, archived in rows}


def test_fresh_database_seeds_dismissed_with_archive_semantics(tmp_path: Path) -> None:
    conn, _session = _open_db(tmp_path)
    flags = _employment_type_flags(conn)
    assert flags["dismissed"] == (True, False)
    assert flags["staff"] == (False, False)
    assert flags["temporary"] == (False, False)
    assert flags["contractor"] == (False, False)
    dismissed_count = conn.execute(
        "SELECT COUNT(*) FROM employment_types WHERE code = ?",
        (DEFAULT_ARCHIVING_EMPLOYMENT_CODE,),
    ).fetchone()[0]
    assert dismissed_count == 1
    conn.close()


def test_archive_sets_is_archived_and_default_archiving_type(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    dismissed_id = conn.execute(
        "SELECT id FROM employment_types WHERE code = ?",
        (DEFAULT_ARCHIVING_EMPLOYMENT_CODE,),
    ).fetchone()[0]
    before_type = conn.execute(
        "SELECT employment_type_id FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()[0]
    employees = EmployeeService(conn, session, clock=lambda: _CLOCK)

    employees.archive_employee(emp_id)

    row = conn.execute(
        "SELECT is_archived, employment_type_id FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert row == (1, dismissed_id)
    assert before_type != dismissed_id
    conn.close()


def test_archive_succeeds_without_archiving_employment_type(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    before_type = conn.execute(
        "SELECT employment_type_id FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()[0]
    conn.execute("UPDATE employment_types SET archives_record = 0 WHERE archives_record = 1")
    conn.commit()
    employees = EmployeeService(conn, session, clock=lambda: _CLOCK)

    employees.archive_employee(emp_id)

    row = conn.execute(
        "SELECT is_archived, employment_type_id FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert row == (1, before_type)
    conn.close()


def test_archive_prefers_dismissed_when_multiple_archiving_types(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    conn.execute(
        "INSERT INTO employment_types (code, name, archives_record, is_archived,"
        " created_at, updated_at) VALUES (?, ?, 1, 0, ?, ?)",
        ("retired", "На пенсии", _CLOCK, _CLOCK),
    )
    conn.commit()
    dismissed_id = conn.execute(
        "SELECT id FROM employment_types WHERE code = ?", (DEFAULT_ARCHIVING_EMPLOYMENT_CODE,)
    ).fetchone()[0]
    employees = EmployeeService(conn, session, clock=lambda: _CLOCK)

    employees.archive_employee(emp_id)

    employment_type_id = conn.execute(
        "SELECT employment_type_id FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()[0]
    assert employment_type_id == dismissed_id
    conn.close()


def test_archive_uses_lexicographic_fallback_without_dismissed(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    conn.execute("DELETE FROM employment_types WHERE code = ?", (DEFAULT_ARCHIVING_EMPLOYMENT_CODE,))
    conn.execute(
        "INSERT INTO employment_types (code, name, archives_record, is_archived,"
        " created_at, updated_at) VALUES (?, ?, 1, 0, ?, ?)",
        ("retired", "На пенсии", _CLOCK, _CLOCK),
    )
    conn.execute(
        "INSERT INTO employment_types (code, name, archives_record, is_archived,"
        " created_at, updated_at) VALUES (?, ?, 1, 0, ?, ?)",
        ("contract_ended", "Контракт завершён", _CLOCK, _CLOCK),
    )
    conn.commit()
    expected_id = conn.execute(
        "SELECT id FROM employment_types WHERE code = ?", ("contract_ended",)
    ).fetchone()[0]
    employees = EmployeeService(conn, session, clock=lambda: _CLOCK)

    employees.archive_employee(emp_id)

    employment_type_id = conn.execute(
        "SELECT employment_type_id FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()[0]
    assert employment_type_id == expected_id
    conn.close()


def test_update_employment_type_does_not_change_is_archived(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    dismissed_id = conn.execute(
        "SELECT id FROM employment_types WHERE code = ?",
        (DEFAULT_ARCHIVING_EMPLOYMENT_CODE,),
    ).fetchone()[0]
    employees = EmployeeService(conn, session, clock=lambda: _CLOCK)
    record = conn.execute(
        "SELECT full_name, position_id, branch_id, department_id, division_id, note"
        " FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()

    employees.update_employee(
        emp_id,
        EmployeeUpdateInput(
            full_name=record[0],
            position_id=record[1],
            branch_id=record[2],
            department_id=record[3],
            division_id=record[4],
            employment_type_id=dismissed_id,
            note=record[5],
        ),
    )

    row = conn.execute(
        "SELECT is_archived, employment_type_id FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert row == (0, dismissed_id)
    conn.close()


def test_restore_clears_archive_without_restoring_previous_employment_type(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    dismissed_id = conn.execute(
        "SELECT id FROM employment_types WHERE code = ?",
        (DEFAULT_ARCHIVING_EMPLOYMENT_CODE,),
    ).fetchone()[0]
    employees = EmployeeService(conn, session, clock=lambda: _CLOCK)

    employees.archive_employee(emp_id)
    employees.restore_employee(emp_id)

    row = conn.execute(
        "SELECT is_archived, employment_type_id, needs_org_review FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert row == (0, dismissed_id, 1)
    conn.close()


def test_status_assignment_does_not_archive_employee(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    history = StatusHistoryService(conn, session, clock=lambda: _CLOCK)

    history.assign_status(emp_id, status_id=1, start_date="2026-09-01")

    row = conn.execute(
        "SELECT is_archived FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()
    assert row == (0,)
    inactive = conn.execute(
        "SELECT id FROM availability_statuses WHERE code = 'inactive'"
    ).fetchone()
    assert inactive is None
    conn.close()


def test_system_dismissed_employment_type_cannot_be_archived(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _CLOCK)
    dismissed_id = conn.execute(
        "SELECT id FROM employment_types WHERE code = ?",
        (DEFAULT_ARCHIVING_EMPLOYMENT_CODE,),
    ).fetchone()[0]

    with pytest.raises(DirectoryError, match="system employment type 'dismissed'"):
        directories.archive_employment_type(dismissed_id)
    conn.close()
