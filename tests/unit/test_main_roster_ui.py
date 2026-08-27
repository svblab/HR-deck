"""UI: доска/таблица, поиск, фильтры, счётчик уточнения (ТЗ §3.4–3.6, §3.3 UI)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QTableWidget

from data.db import Connection
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
