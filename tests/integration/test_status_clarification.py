"""Integration: «Требует уточнения статуса» (EPIC-007)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import Connection
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.status_clarification import StatusClarificationService
from services.status_history import StatusHistoryService
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


def _observer_session(conn: Connection, admin: SessionState, db: Path) -> SessionState:
    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-08-26T12:01:00Z"
    )
    obs_id = mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    return SessionState(
        account_id=obs_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=admin.master_key,
    )


@pytest.mark.acceptance
def test_expired_status_appears_in_clarification_list(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-15T10:00:00Z")
    clarify = StatusClarificationService(conn, session, clock=lambda: "2026-08-15T10:00:00Z")
    emp = ids["employee_a_id"]
    history.assign_status(
        emp,
        status_id=3,
        start_date="2026-08-01",
        end_date="2026-08-10",
    )
    assert clarify.count_needing_clarification(as_of="2026-08-11") == 2
    hits = clarify.list_needing_clarification(as_of="2026-08-11")
    hit = next(h for h in hits if h.employee_id == emp)
    assert hit.last_status_id == 3
    assert hit.last_status_end_date == "2026-08-10"
    assert hit.last_status_name == "Командировка"
    conn.close()


@pytest.mark.acceptance
def test_open_status_excluded_from_clarification(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    clarify = StatusClarificationService(conn, session, clock=lambda: "2026-08-15T10:00:00Z")
    history.assign_status(ids["employee_a_id"], status_id=2, start_date="2026-08-01")
    assert clarify.count_needing_clarification(as_of="2026-08-15") == 1
    assert not clarify.employee_needs_clarification(ids["employee_a_id"], as_of="2026-08-15")
    conn.close()


@pytest.mark.acceptance
def test_startup_count_snapshot(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    seed_synthetic_org(conn)
    clarify = StatusClarificationService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    snap = clarify.startup_clarification_count()
    assert snap.as_of_date == "2026-08-01"
    assert snap.count == 2
    assert clarify.persistent_counter_snapshot().count == 2
    conn.close()


@pytest.mark.acceptance
def test_filter_needing_clarification_subset(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    clarify = StatusClarificationService(conn, session, clock=lambda: "2026-08-15T10:00:00Z")
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    both = [ids["employee_a_id"], ids["employee_b_id"]]
    filtered = clarify.filter_needing_clarification(both, as_of="2026-08-15")
    assert filtered == [ids["employee_b_id"]]
    conn.close()


@pytest.mark.acceptance
def test_no_status_history_needs_clarification(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    clarify = StatusClarificationService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    assert clarify.employee_needs_clarification(ids["employee_b_id"])
    conn.close()


@pytest.mark.acceptance
def test_observer_can_view_clarification_list(tmp_path: Path) -> None:
    conn, admin, db = _open_db(tmp_path)
    seed_synthetic_org(conn)
    obs = _observer_session(conn, admin, db)
    clarify = StatusClarificationService(conn, obs, clock=lambda: "2026-08-01T10:00:00Z")
    assert clarify.count_needing_clarification() == 2
    conn.close()


def test_clarification_is_read_only_no_audit(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    seed_synthetic_org(conn)
    clarify = StatusClarificationService(conn, session, clock=lambda: "2026-08-01T10:00:00Z")
    before = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    clarify.list_needing_clarification()
    after = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after == before
    conn.close()
