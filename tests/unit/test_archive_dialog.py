"""UI: экран архива уволенных сотрудников."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox, QPushButton, QTableWidget, QToolButton

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationService
from services.availability_statuses import AvailabilityStatusService
from services.bootstrap import BootstrapService
from services.employees import EmployeeService
from services.roster import RosterService
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.archive_dialog import ArchiveDialog
from ui.board_widget import EmployeeCardWidget
from ui.main_window import MainWindow
from ui.roster_panel import RosterPanel


def _ensure_dismissed(conn, clock: str = "2026-08-30T10:00:00Z") -> None:
    if conn.execute("SELECT 1 FROM employment_types WHERE code = 'dismissed'").fetchone():
        return
    conn.execute(
        "INSERT INTO employment_types (code, name, is_archived, created_at, updated_at)"
        " VALUES (?, ?, 0, ?, ?)",
        ("dismissed", "Уволен", clock, clock),
    )
    conn.commit()


def _admin_window(tmp_path: Path) -> tuple[MainWindow, object, object, dict[str, int]]:
    db = tmp_path / "app.db"
    clock = lambda: "2026-08-30T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    _ensure_dismissed(conn)
    history = StatusHistoryService(conn, session, clock=clock)
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    window = MainWindow(conn=conn, session=session, db_path=db)
    return window, conn, session, ids


def test_archive_button_hidden_for_observer(qtbot, tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    clock = lambda: "2026-08-30T12:00:00Z"  # noqa: E731
    conn, admin, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    seed_synthetic_org(conn)
    mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
    mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn2, obs_session = auth.login(db_path=db, login="obs1", password="ObsPass-1")
    window = MainWindow(conn=conn2, session=obs_session, db_path=db)
    qtbot.addWidget(window)
    matching = [btn for btn in window.findChildren(QToolButton) if btn.toolTip() == "Архив"]
    assert len(matching) == 1
    assert matching[0].isHidden()
    window.close()
    conn.close()
    conn2.close()


def test_archive_dialog_lists_archived_employee(qtbot, tmp_path: Path) -> None:
    window, conn, session, ids = _admin_window(tmp_path)
    qtbot.addWidget(window)
    employees = EmployeeService(conn, session, clock=lambda: "2026-08-30T12:00:00Z")
    employees.archive_employee(ids["employee_a_id"])

    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-30T12:00:00Z")
    dialog = ArchiveDialog(
        RosterService(conn, session, clock=lambda: "2026-08-30T12:00:00Z"),
        employees,
        history,
        AvailabilityStatusService(conn, session),
        session,
    )
    qtbot.addWidget(dialog)

    table = dialog.findChild(QTableWidget, "archiveTable")
    assert table is not None
    assert table.rowCount() == 1
    assert table.item(0, 0) is not None
    assert "Иванов" in table.item(0, 0).text()

    dialog.close()
    window.close()
    conn.close()


def test_archive_restore_returns_employee_to_main_board(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, conn, session, ids = _admin_window(tmp_path)
    qtbot.addWidget(window)
    emp_id = ids["employee_a_id"]
    employees = EmployeeService(conn, session, clock=lambda: "2026-08-30T12:00:00Z")
    employees.archive_employee(emp_id)
    panel = window.findChild(RosterPanel)
    assert panel is not None
    panel.reload()
    qtbot.waitUntil(lambda: len(panel.findChildren(EmployeeCardWidget)) == 1)

    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-30T12:00:00Z")
    dialog = ArchiveDialog(
        RosterService(conn, session, clock=lambda: "2026-08-30T12:00:00Z"),
        employees,
        history,
        AvailabilityStatusService(conn, session),
        session,
        on_changed=panel.reload,
        parent=window,
    )
    qtbot.addWidget(dialog)
    table = dialog.findChild(QTableWidget, "archiveTable")
    assert table is not None
    table.selectRow(0)
    restore_btn = dialog.findChild(QPushButton, "archiveRestoreBtn")
    assert restore_btn is not None
    restore_btn.click()

    qtbot.waitUntil(lambda: len(panel.findChildren(EmployeeCardWidget)) == 2)
    dialog.close()
    window.close()
    conn.close()


def test_archive_restore_and_assign_uses_status_dialog(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog

    from ui.status_assign_dialog import StatusAssignDialog

    window, conn, session, ids = _admin_window(tmp_path)
    qtbot.addWidget(window)
    emp_id = ids["employee_a_id"]
    employees = EmployeeService(conn, session, clock=lambda: "2026-08-30T12:00:00Z")
    employees.archive_employee(emp_id)

    opened: list[int] = []
    original_init = StatusAssignDialog.__init__

    def _track_init(self, *args, **kwargs) -> None:  # noqa: ANN002
        opened.append(1)
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(StatusAssignDialog, "__init__", _track_init)
    monkeypatch.setattr(
        StatusAssignDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-30T12:00:00Z")
    dialog = ArchiveDialog(
        RosterService(conn, session, clock=lambda: "2026-08-30T12:00:00Z"),
        employees,
        history,
        AvailabilityStatusService(conn, session),
        session,
        parent=window,
    )
    qtbot.addWidget(dialog)
    table = dialog.findChild(QTableWidget, "archiveTable")
    assert table is not None
    table.selectRow(0)
    assign_btn = dialog.findChild(QPushButton, "archiveRestoreAssignBtn")
    assert assign_btn is not None
    assign_btn.click()

    assert opened == [1]
    assert (
        conn.execute("SELECT is_archived FROM employees WHERE id = ?", (emp_id,)).fetchone()[0] == 0
    )

    dialog.close()
    window.close()
    conn.close()
