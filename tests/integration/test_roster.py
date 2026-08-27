"""Integration: проекция главного экрана, без записей аудита (EPIC-008)."""

from __future__ import annotations

from pathlib import Path

from data.db import Connection
from domain.roster import GroupBy, RosterFilters
from services.bootstrap import BootstrapService
from services.roster import RosterService
from services.session import SessionState
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org


def _open(tmp_path: Path) -> tuple[Connection, SessionState]:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-15T12:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


def test_roster_marks_expired_and_excludes_open_status(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-15T12:00:00Z")
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    history.assign_status(
        ids["employee_b_id"],
        status_id=3,
        start_date="2026-08-01",
        end_date="2026-08-10",
    )
    roster = RosterService(conn, session, clock=lambda: "2026-08-15T12:00:00Z")
    rows = {r.employee_id: r for r in roster.list_rows(as_of="2026-08-15")}
    assert rows[ids["employee_a_id"]].needs_clarification is False
    assert rows[ids["employee_a_id"]].status_id == 1
    assert rows[ids["employee_b_id"]].needs_clarification is True
    assert rows[ids["employee_b_id"]].status_id == 3
    filtered = roster.list_rows(
        as_of="2026-08-15",
        filters=RosterFilters(only_needing_clarification=True),
    )
    assert [r.employee_id for r in filtered] == [ids["employee_b_id"]]
    specs = roster.column_specs(GroupBy.STATUS)
    assert any(s.title == "В офисе" for s in specs)
    conn.close()


def test_roster_read_does_not_write_audit(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    seed_synthetic_org(conn)
    roster = RosterService(conn, session, clock=lambda: "2026-08-15T12:00:00Z")
    before = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    roster.list_rows()
    roster.column_specs(GroupBy.BRANCH)
    roster.filter_departments(branch_id=1)
    after = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after == before
    conn.close()
