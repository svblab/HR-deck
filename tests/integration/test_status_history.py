"""Integration: статусы доступности и история (EPIC-006)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import Connection
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authorization import AuthorizationError
from services.availability_statuses import AvailabilityStatusError, AvailabilityStatusService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.status_history import ConfirmationRequiredError, StatusHistoryService
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


def _hr_session(conn: Connection, admin: SessionState, db: Path) -> SessionState:
    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-08-26T12:01:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    return SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin.master_key,
    )


def _observer_session(conn: Connection, admin: SessionState, db: Path) -> SessionState:
    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-08-26T12:02:00Z"
    )
    obs_id = mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    return SessionState(
        account_id=obs_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=admin.master_key,
    )


@pytest.mark.acceptance
def test_status_directory_crud_and_archive(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    svc = AvailabilityStatusService(conn, session, clock=lambda: "2026-08-26T13:00:00Z")
    status_id = svc.create_status(code="training", name="Обучение", end_date_policy=2)
    svc.rename_status(status_id, "Обучение (внутр.)")
    svc.archive_status(status_id)
    active = {s.id for s in svc.list_statuses(active_only=True)}
    assert status_id not in active
    audit = conn.execute(
        "SELECT action_type FROM user_action_log WHERE entity_type='availability_status'"
        " AND entity_id=?",
        (status_id,),
    ).fetchall()
    actions = {r[0] for r in audit}
    assert "status.create" in actions
    assert "status.rename" in actions
    assert "status.archive" in actions
    conn.close()


@pytest.mark.acceptance
def test_auto_close_previous_open_period(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    svc = StatusHistoryService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    emp = ids["employee_a_id"]
    svc.assign_status(emp, status_id=2, start_date="2026-08-01")
    svc.assign_status(emp, status_id=1, start_date="2026-09-01")
    timeline = svc.effective_timeline(emp)
    assert len(timeline) == 2
    assert timeline[0].end_date == "2026-08-31"
    assert timeline[1].start_date == "2026-09-01"
    corrections = conn.execute(
        "SELECT reason FROM status_history_corrections"
    ).fetchall()
    assert any(r[0] == "auto_close" for r in corrections)
    conn.close()


@pytest.mark.acceptance
def test_future_status_not_current_until_start(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    svc = StatusHistoryService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    emp = ids["employee_a_id"]
    svc.assign_status(emp, status_id=2, start_date="2026-08-01")
    svc.assign_status(
        emp,
        status_id=5,
        start_date="2026-10-01",
        end_date="2026-10-14",
    )
    current = svc.current_status(emp, as_of="2026-08-15")
    assert current is not None
    assert current.status_id == 2
    conn.close()


@pytest.mark.acceptance
def test_backdate_requires_confirmation_and_preserves_audit(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    svc = StatusHistoryService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    emp = ids["employee_a_id"]
    svc.assign_status(
        emp,
        status_id=1,
        start_date="2026-08-01",
        end_date="2026-08-31",
    )
    with pytest.raises(ConfirmationRequiredError) as exc:
        svc.assign_status(
            emp,
            status_id=4,
            start_date="2026-08-10",
            end_date="2026-08-12",
        )
    plan = exc.value.plan
    svc.apply_plan(emp, plan, confirmed=True)
    raw_count = conn.execute(
        "SELECT COUNT(*) FROM status_history WHERE employee_id=?", (emp,)
    ).fetchone()[0]
    corr_count = conn.execute("SELECT COUNT(*) FROM status_history_corrections").fetchone()[0]
    assert raw_count == 3  # original + sick leave + office tail
    assert corr_count >= 1
    timeline = svc.effective_timeline(emp)
    sick = next(r for r in timeline if r.status_id == 4)
    assert sick.start_date == "2026-08-10"
    assert sick.end_date == "2026-08-12"
    conn.close()


@pytest.mark.acceptance
def test_overlap_rejected_without_confirmed_flow(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    svc = StatusHistoryService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    emp = ids["employee_a_id"]
    svc.assign_status(
        emp,
        status_id=1,
        start_date="2026-08-01",
        end_date="2026-08-31",
    )
    with pytest.raises(ConfirmationRequiredError):
        svc.assign_status(
            emp,
            status_id=2,
            start_date="2026-08-15",
            end_date="2026-09-05",
            confirmed=False,
        )
    conn.close()


@pytest.mark.acceptance
def test_rbac_hr_manages_observer_read_only(tmp_path: Path) -> None:
    conn, admin, db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    hr = _hr_session(conn, admin, db)
    obs = _observer_session(conn, admin, db)
    hr_svc = StatusHistoryService(conn, hr, clock=lambda: "2026-08-26T14:00:00Z")
    obs_svc = StatusHistoryService(conn, obs, clock=lambda: "2026-08-26T14:00:01Z")
    hr_svc.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    assert obs_svc.list_history(ids["employee_a_id"])
    with pytest.raises(AuthorizationError):
        obs_svc.assign_status(ids["employee_a_id"], status_id=2, start_date="2026-09-01")
    conn.close()


@pytest.mark.acceptance
def test_assign_status_writes_audit_log(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    svc = StatusHistoryService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    emp = ids["employee_a_id"]
    before = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    svc.assign_status(emp, status_id=1, start_date="2026-08-01")
    after = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after == before + 1
    row = conn.execute(
        "SELECT action_type, entity_type, entity_id FROM user_action_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row[0] == "status.assign"
    assert row[1] == "employee"
    assert row[2] == emp
    conn.close()


@pytest.mark.acceptance
def test_migration_0007_on_nonempty_db(tmp_path: Path) -> None:
    """Миграция 0007 на непустой БД: таблица corrections, данные сохранены."""
    from data.db import connect, create_database, generate_master_key
    from data.migrations import apply_pending_migrations, current_version

    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn)
    ids = seed_synthetic_org(conn)
    conn.execute(
        "INSERT INTO status_history (employee_id, status_id, start_date, created_at)"
        " VALUES (?, 1, '2026-08-01', '2026-08-01T10:00:00Z')",
        (ids["employee_a_id"],),
    )
    conn.commit()
    emp_name = conn.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0]
    conn.close()

    conn2 = connect(path, key)
    assert apply_pending_migrations(conn2) == []
    assert current_version(conn2) >= 7
    tables = {
        r[0]
        for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "status_history_corrections" in tables
    row = conn2.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()
    assert row[0] == emp_name
    hist = conn2.execute("SELECT COUNT(*) FROM status_history").fetchone()[0]
    assert hist == 1
    conn2.close()


def test_status_code_unique(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    svc = AvailabilityStatusService(conn, session, clock=lambda: "2026-08-26T15:00:00Z")
    svc.create_status(code="custom", name="Custom")
    with pytest.raises(AvailabilityStatusError, match="code already exists"):
        svc.create_status(code="custom", name="Other")
    conn.close()
