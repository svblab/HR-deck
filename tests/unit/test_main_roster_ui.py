"""UI: доска/таблица, поиск, фильтры, счётчик уточнения (ТЗ §3.4–3.6, §3.3 UI)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QToolButton,
    QWidget,
)

from data.db import Connection
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.board_widget import BoardWidget, EmployeeCardWidget
from ui.main_window import MainWindow
from ui.roster_panel import RosterPanel


def _window(tmp_path: Path) -> tuple[MainWindow, Connection, SessionState, dict[str, int]]:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-15T12:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-15T12:00:00Z")
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    window = MainWindow(conn=conn, session=session, db_path=db)
    return window, conn, session, ids


def test_search_enabled_and_filters_roster(qtbot, tmp_path: Path) -> None:
    window, conn, _session, _ids = _window(tmp_path)
    qtbot.addWidget(window)
    search = window.findChild(QLineEdit, "searchInput")
    assert search is not None
    assert search.isEnabled()
    search.setText("неттакого")
    panel = window.findChild(RosterPanel)
    assert panel is not None
    qtbot.waitUntil(lambda: len(panel.findChildren(EmployeeCardWidget)) == 0)
    window.findChild(QPushButton, "filterReset").click()
    qtbot.waitUntil(lambda: len(panel.findChildren(EmployeeCardWidget)) == 2)
    window.close()
    conn.close()


def test_board_table_toggle_and_clarification_counter(qtbot, tmp_path: Path) -> None:
    window, conn, _session, _ids = _window(tmp_path)
    qtbot.addWidget(window)
    counter = window.findChild(QPushButton, "clarificationCounter")
    assert counter is not None
    assert not counter.isHidden()
    assert "1" in counter.text()
    window.show()
    table_btn = window.findChild(QPushButton, "viewToggleInactive")
    assert table_btn is not None
    table_btn.click()
    table = window.findChild(QTableWidget, "rosterTable")
    assert table is not None
    assert table.rowCount() == 2
    panel = window.findChild(RosterPanel)
    assert panel is not None
    assert panel._stack.currentIndex() == 1
    window.close()
    conn.close()


def test_popup_opens_from_card(qtbot, tmp_path: Path) -> None:
    window, conn, _session, _ids = _window(tmp_path)
    qtbot.addWidget(window)
    panel = window.findChild(RosterPanel)
    assert panel is not None
    cards = panel.findChildren(EmployeeCardWidget)
    assert cards
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog

    def _close() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible() and widget is not window:
                widget.accept()
                return

    QTimer.singleShot(0, _close)
    cards[0].clicked.emit(cards[0]._employee_id)
    window.close()
    conn.close()


def test_shell_without_session_still_builds(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.findChild(QLabel, "logoBadge") is not None
    assert window.findChild(BoardWidget) is None
    window.close()


def test_add_button_enabled_reports_open(qtbot, tmp_path: Path) -> None:
    window, conn, _session, _ids = _window(tmp_path)
    qtbot.addWidget(window)
    add_btn = window.findChild(QPushButton, "addEmployeeBtn")
    assert add_btn is not None
    assert add_btn.isEnabled()
    reports = window.findChild(QPushButton, "reportsBtn")
    assert reports is not None
    assert reports.isEnabled()
    templates = window.findChild(QPushButton, "templatesBtn")
    assert templates is not None
    assert templates.isEnabled()
    assert window.findChild(QPushButton, "importEmployeesBtn").isEnabled()
    assert window.findChild(QPushButton, "exportEmployeesBtn").isEnabled()
    window.close()
    conn.close()


def test_add_button_opens_form_save_reloads_roster(qtbot, tmp_path: Path) -> None:
    window, conn, _session, _ids = _window(tmp_path)
    qtbot.addWidget(window)
    add_btn = window.findChild(QPushButton, "addEmployeeBtn")
    assert add_btn is not None
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from ui.employee_card_form import EmployeeCardDialog

    def _fill_and_save() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, EmployeeCardDialog) and widget.isVisible():
                widget._name.setText("Сидорова Анна")
                widget._position.setCurrentIndex(1)
                widget._branch.setCurrentIndex(1)
                widget._department.setCurrentIndex(1)
                widget._division.setCurrentIndex(1)
                widget._employment.setCurrentIndex(1)
                widget._submit()
                return

    QTimer.singleShot(0, _fill_and_save)
    add_btn.click()
    panel = window.findChild(RosterPanel)
    assert panel is not None
    qtbot.waitUntil(lambda: len(panel.findChildren(EmployeeCardWidget)) == 3)
    window.close()
    conn.close()


def test_clarification_counter_hidden_when_none_need_clarification(
    qtbot, tmp_path: Path
) -> None:
    db = tmp_path / "plain.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-15T12:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=lambda: "2026-08-15T12:00:00Z")
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    history.assign_status(ids["employee_b_id"], status_id=1, start_date="2026-08-01")
    window = MainWindow(conn=conn, session=session, db_path=db)
    qtbot.addWidget(window)
    counter = window.findChild(QPushButton, "clarificationCounter")
    clarify_filter = window.findChild(QCheckBox, "clarifyFilter")
    assert counter is not None and counter.isHidden()
    assert clarify_filter is not None and clarify_filter.isHidden()
    window.close()
    conn.close()


def _session_for_role(
    conn: Connection,
    admin: SessionState,
    db: Path,
    role: RoleCode,
) -> SessionState:
    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-08-15T12:01:00Z"
    )
    if role == RoleCode.HR_EMPLOYEE:
        account_id = mgr.create_account(
            login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE
        )
        login = "hr1"
    else:
        account_id = mgr.create_account(
            login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER
        )
        login = "obs1"
    return SessionState(
        account_id=account_id,
        login=login,
        role=role,
        master_key=admin.master_key,
    )


def test_observer_roster_shows_read_only_toolbar(qtbot, tmp_path: Path) -> None:
    window, conn, session, _ids = _window(tmp_path)
    obs = _session_for_role(conn, session, tmp_path / "app.db", RoleCode.OBSERVER)
    window.close()
    obs_window = MainWindow(conn=conn, session=obs, db_path=tmp_path / "app.db")
    qtbot.addWidget(obs_window)
    toolbar = obs_window.findChild(QWidget, "toolbarRole_observer")
    assert toolbar is not None
    assert obs_window.findChild(QPushButton, "addEmployeeBtn") is None
    assert obs_window.findChild(QPushButton, "importEmployeesBtn") is None
    assert obs_window.findChild(QPushButton, "exportEmployeesBtn") is None
    assert obs_window.findChild(QPushButton, "reportsBtn") is not None
    assert obs_window.findChild(QPushButton, "directoriesBtn") is not None
    assert obs_window.findChild(QPushButton, "templatesBtn") is not None
    backup = next(
        btn
        for btn in obs_window.findChildren(QToolButton)
        if btn.toolTip() == "Резервное копирование"
    )
    assert backup.isHidden()
    obs_window.close()
    conn.close()


def test_hr_roster_includes_write_actions_without_admin_tools(
    qtbot, tmp_path: Path
) -> None:
    window, conn, session, _ids = _window(tmp_path)
    db = tmp_path / "app.db"
    hr = _session_for_role(conn, session, db, RoleCode.HR_EMPLOYEE)
    window.close()
    hr_window = MainWindow(conn=conn, session=hr, db_path=db)
    qtbot.addWidget(hr_window)
    assert hr_window.findChild(QWidget, "toolbarRole_hr_employee") is not None
    assert hr_window.findChild(QPushButton, "addEmployeeBtn") is not None
    assert hr_window.findChild(QPushButton, "importEmployeesBtn") is not None
    assert hr_window.findChild(QPushButton, "exportEmployeesBtn") is not None
    assert hr_window.findChild(QToolButton, "actionLogBtn").isHidden()
    hr_window.close()
    conn.close()


def test_action_log_button_visible_for_admin(qtbot, tmp_path: Path) -> None:
    window, conn, _session, _ids = _window(tmp_path)
    qtbot.addWidget(window)
    btn = window.findChild(QToolButton, "actionLogBtn")
    assert btn is not None
    assert not btn.isHidden()
    assert btn.isEnabled()
    window.close()
    conn.close()


def test_action_log_button_hidden_for_hr(qtbot, tmp_path: Path) -> None:
    window, conn, session, _ids = _window(tmp_path)
    db = tmp_path / "app.db"
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-15T12:01:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    hr = SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=session.master_key,
    )
    window.close()
    hr_window = MainWindow(conn=conn, session=hr, db_path=db)
    qtbot.addWidget(hr_window)
    btn = hr_window.findChild(QToolButton, "actionLogBtn")
    assert btn is not None
    assert btn.isHidden()
    hr_window.close()
    conn.close()


def test_show_archived_toggle_reveals_archived_employee(qtbot, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QCheckBox

    from services.employees import EmployeeService

    window, conn, session, ids = _window(tmp_path)
    qtbot.addWidget(window)
    EmployeeService(conn, session, clock=lambda: "2026-08-15T12:05:00Z").archive_employee(
        ids["employee_a_id"]
    )
    panel = window.findChild(RosterPanel)
    assert panel is not None
    panel.reload()
    qtbot.waitUntil(lambda: len(panel.findChildren(EmployeeCardWidget)) == 1)

    before = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    toggle = panel.findChild(QCheckBox, "showArchivedFilter")
    assert toggle is not None
    toggle.setChecked(True)
    qtbot.waitUntil(lambda: len(panel.findChildren(EmployeeCardWidget)) == 2)
    after = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after == before

    window.close()
    conn.close()
