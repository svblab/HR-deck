"""Integration: MainWindow reconnects roster after backup restore (EPIC-016 §4 item 5 gap)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlcipher3.dbapi2 import ProgrammingError

from services.backup import BackupService
from services.bootstrap import BootstrapService
from services.roster import RosterService
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.main_window import MainWindow


def _open(tmp_path: Path):
    clock = lambda: "2026-08-30T15:00:00Z"  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=clock)
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    backup = BackupService(conn, session, db_path=db, clock=clock)
    return db, conn, session, backup, ids, clock


def _row_for(window: MainWindow, employee_id: int):
    assert window._roster is not None
    return next(
        (r for r in window._roster._all_rows if r.employee_id == employee_id),
        None,
    )


@pytest.mark.acceptance
def test_replace_connection_reloads_roster_from_restored_db(
    qtbot, tmp_path: Path
) -> None:
    db, conn, session, backup, ids, _clock = _open(tmp_path)
    emp_id = ids["employee_a_id"]
    original_name = "Иванов Иван Иванович"

    window = MainWindow(conn=conn, session=session, db_path=db)
    qtbot.addWidget(window)
    assert window._roster is not None
    before = _row_for(window, emp_id)
    assert before is not None
    assert before.full_name == original_name
    assert before.status_id == 1
    stale_service = window._roster._service
    assert isinstance(stale_service, RosterService)

    snapshot = backup.create_backup(tmp_path / "external")
    conn.execute(
        "UPDATE employees SET full_name = ? WHERE id = ?",
        ("После бэкапа", emp_id),
    )
    conn.commit()
    window._roster.reload()
    mutated = _row_for(window, emp_id)
    assert mutated is not None
    assert mutated.full_name == "После бэкапа"

    new_conn = backup.restore_backup(snapshot)
    with pytest.raises(ProgrammingError, match="closed database"):
        conn.execute("SELECT 1")

    window._replace_connection(new_conn)

    assert window._conn is new_conn
    assert window._roster._service is not stale_service
    assert isinstance(window._roster._service, RosterService)
    restored = _row_for(window, emp_id)
    assert restored is not None
    assert restored.full_name == original_name
    assert restored.status_id == 1

    window._roster.reload()
    again = _row_for(window, emp_id)
    assert again is not None
    assert again.full_name == original_name

    window.close()
    new_conn.close()


@pytest.mark.acceptance
def test_replace_connection_noop_when_roster_missing(qtbot, tmp_path: Path) -> None:
    db, conn, session, backup, _ids, _clock = _open(tmp_path)
    snapshot = backup.create_backup(tmp_path / "external")
    new_conn = backup.restore_backup(snapshot)

    window = MainWindow()
    qtbot.addWidget(window)
    assert window._roster is None

    window._replace_connection(new_conn)
    assert window._conn is new_conn
    assert window._roster is None

    window.close()
    new_conn.close()
