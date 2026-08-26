"""Integration: справочники CRUD, архив, RBAC, аудит (EPIC-004)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import Connection
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.directories import DirectoryError, DirectoryService
from services.session import SessionState
from tests.fixtures.synthetic import seed_synthetic_org


def _open_db(tmp_path: Path) -> tuple[Connection, SessionState, Path]:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-26T12:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session, db


def _hr_session(conn: Connection, admin_session: SessionState, db: Path) -> SessionState:
    mgr = AccountManagementService(
        conn, admin_session, db_path=db, clock=lambda: "2026-08-26T12:01:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    return SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin_session.master_key,
    )


def _observer_session(conn: Connection, admin_session: SessionState, db: Path) -> SessionState:
    mgr = AccountManagementService(
        conn, admin_session, db_path=db, clock=lambda: "2026-08-26T12:02:00Z"
    )
    obs_id = mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    return SessionState(
        account_id=obs_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=admin_session.master_key,
    )


@pytest.mark.acceptance
def test_branch_crud_rename_preserves_id_and_audit(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: "2026-08-26T13:00:00Z")
    branch_id = svc.create_branch("Филиал Альфа")
    svc.rename_branch(branch_id, "Филиал Альфа-1")
    row = conn.execute("SELECT name FROM branches WHERE id = ?", (branch_id,)).fetchone()
    assert row[0] == "Филиал Альфа-1"
    audit = conn.execute(
        "SELECT action_type FROM user_action_log WHERE entity_type='branch' AND entity_id=?",
        (branch_id,),
    ).fetchall()
    actions = {r[0] for r in audit}
    assert "directory.branch.create" in actions
    assert "directory.branch.rename" in actions
    conn.close()


@pytest.mark.acceptance
def test_cascade_branch_department_division(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: "2026-08-26T13:10:00Z")
    branch_id = svc.create_branch("Бета")
    dept_id = svc.create_department(branch_id, "Департамент IT")
    div_id = svc.create_division(dept_id, "Отдел платформы")
    assert len(svc.list_departments(branch_id=branch_id)) >= 1
    assert len(svc.list_divisions(department_id=dept_id)) == 1
    assert svc.list_divisions(department_id=dept_id)[0].id == div_id
    conn.close()


@pytest.mark.acceptance
def test_archive_excluded_from_active_only(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: "2026-08-26T13:20:00Z")
    pos_id = svc.create_position("Инженер-тест")
    svc.archive_position(pos_id)
    active_ids = {p.id for p in svc.list_positions(active_only=True)}
    all_ids = {p.id for p in svc.list_positions(active_only=False)}
    assert pos_id not in active_ids
    assert pos_id in all_ids
    conn.close()


@pytest.mark.acceptance
def test_rename_preserves_employee_fk(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    svc = DirectoryService(conn, session, clock=lambda: "2026-08-26T13:30:00Z")
    svc.rename_branch(ids["branch_id"], "Филиал переименован")
    emp = conn.execute(
        "SELECT branch_id FROM employees WHERE id = ?", (ids["employee_a_id"],)
    ).fetchone()
    assert emp[0] == ids["branch_id"]
    conn.close()


@pytest.mark.acceptance
def test_hr_can_manage_observer_cannot(tmp_path: Path) -> None:
    conn, admin, db = _open_db(tmp_path)
    hr = _hr_session(conn, admin, db)
    obs = _observer_session(conn, admin, db)
    hr_svc = DirectoryService(conn, hr, clock=lambda: "2026-08-26T13:40:00Z")
    obs_svc = DirectoryService(conn, obs, clock=lambda: "2026-08-26T13:40:01Z")
    branch_id = hr_svc.create_branch("Гamma")
    assert obs_svc.list_branches()
    with pytest.raises(AuthorizationError):
        obs_svc.create_branch("Denied")
    hr_svc.archive_branch(branch_id)
    conn.close()


@pytest.mark.acceptance
def test_cannot_create_under_archived_parent(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: "2026-08-26T13:50:00Z")
    branch_id = svc.create_branch("Archived parent")
    svc.archive_branch(branch_id)
    with pytest.raises(DirectoryError, match="archived branch"):
        svc.create_department(branch_id, "Should fail")
    conn.close()


@pytest.mark.acceptance
def test_employment_type_code_unique(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: "2026-08-26T14:00:00Z")
    svc.create_employment_type("intern", "Стажёр")
    with pytest.raises(DirectoryError, match="code already exists"):
        svc.create_employment_type("intern", "Другой")
    conn.close()


def test_failed_create_no_audit(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: "2026-08-26T14:10:00Z")
    before = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    with pytest.raises(DirectoryError):
        svc.create_branch("   ")
    after = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after == before
    conn.close()
