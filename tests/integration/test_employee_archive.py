"""Integration: архивирование сотрудников (EPIC-014, ТЗ §3.9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import Connection
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.employees import EmployeeService
from services.roster import RosterService
from services.session import SessionState
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org


def _open_db(tmp_path: Path) -> tuple[Connection, SessionState, Path]:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-30T10:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session, db


def _observer_session(conn: Connection, admin: SessionState, db: Path) -> SessionState:
    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-08-30T10:01:00Z"
    )
    obs_id = mgr.create_account(
        login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER
    )
    return SessionState(
        account_id=obs_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=admin.master_key,
    )


def _history_rows(conn: Connection, employee_id: int) -> list[tuple]:
    return conn.execute(
        "SELECT id, status_id, start_date, end_date, note, created_at,"
        " created_by_account_id"
        " FROM status_history WHERE employee_id = ? ORDER BY id",
        (employee_id,),
    ).fetchall()


@pytest.mark.acceptance
def test_archive_restore_hides_and_shows_in_roster(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    employees = EmployeeService(conn, session, clock=lambda: "2026-08-30T10:10:00Z")
    roster = RosterService(conn, session, clock=lambda: "2026-08-30T10:10:00Z")

    assert any(r.employee_id == emp_id for r in roster.list_rows())

    employees.archive_employee(emp_id)
    assert not any(r.employee_id == emp_id for r in roster.list_rows())
    assert any(r.employee_id == emp_id for r in roster.list_rows(include_archived=True))

    employees.restore_employee(emp_id)
    assert any(r.employee_id == emp_id for r in roster.list_rows())
    conn.close()


@pytest.mark.acceptance
def test_status_history_survives_archive_restore(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-30T10:20:00Z")
    history.assign_status(emp_id, status_id=1, start_date="2026-08-01")
    history.assign_status(emp_id, status_id=2, start_date="2026-08-10", end_date="2026-08-14")
    before = _history_rows(conn, emp_id)

    employees = EmployeeService(conn, session, clock=lambda: "2026-08-30T10:21:00Z")
    employees.archive_employee(emp_id)
    employees.restore_employee(emp_id)
    after = _history_rows(conn, emp_id)

    assert after == before
    conn.close()


@pytest.mark.acceptance
def test_archive_restore_idempotent_no_duplicate_audit(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    svc = EmployeeService(conn, session, clock=lambda: "2026-08-30T10:30:00Z")

    svc.archive_employee(emp_id)
    archive_count = conn.execute(
        "SELECT COUNT(*) FROM user_action_log WHERE action_type = 'employee.archive'"
    ).fetchone()[0]
    svc.archive_employee(emp_id)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM user_action_log WHERE action_type = 'employee.archive'"
        ).fetchone()[0]
        == archive_count
    )

    svc.restore_employee(emp_id)
    restore_count = conn.execute(
        "SELECT COUNT(*) FROM user_action_log WHERE action_type = 'employee.restore'"
    ).fetchone()[0]
    svc.restore_employee(emp_id)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM user_action_log WHERE action_type = 'employee.restore'"
        ).fetchone()[0]
        == restore_count
    )
    conn.close()


@pytest.mark.acceptance
def test_observer_cannot_archive(tmp_path: Path) -> None:
    conn, admin, db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    obs = _observer_session(conn, admin, db)
    admin_svc = EmployeeService(conn, admin, clock=lambda: "2026-08-30T10:40:00Z")
    obs_svc = EmployeeService(conn, obs, clock=lambda: "2026-08-30T10:40:01Z")
    admin_svc.archive_employee(ids["employee_a_id"])
    with pytest.raises(AuthorizationError):
        obs_svc.restore_employee(ids["employee_a_id"])
    conn.close()


@pytest.mark.acceptance
def test_inactive_status_auto_archives(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-30T10:50:00Z")
    history.assign_status(emp_id, status_id=7, start_date="2026-08-20")

    row = conn.execute(
        "SELECT is_archived FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()
    assert row[0] == 1
    conn.close()


def test_search_by_name_stays_active_only(tmp_path: Path) -> None:
    """Duplicate-hint search ignores archived employees even when roster shows archive."""
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    card = conn.execute(
        "SELECT full_name FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()[0]
    prefix = card[:4]
    employees = EmployeeService(conn, session, clock=lambda: "2026-08-30T11:00:00Z")
    assert any(h.id == emp_id for h in employees.search_by_name(prefix))

    employees.archive_employee(emp_id)
    assert not any(h.id == emp_id for h in employees.search_by_name(prefix))
    conn.close()
