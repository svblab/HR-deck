"""UI acceptance: search → card → status (EPIC-016 §4 checklist item 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDateEdit,
    QLabel,
    QLineEdit,
    QPushButton,
)

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.board_widget import EmployeeCardWidget
from ui.employee_card_form import EmployeeCardDialog
from ui.employee_popup import EmployeePopupDialog
from ui.main_window import MainWindow
from ui.roster_panel import RosterPanel
from ui.status_assign_dialog import StatusAssignDialog

_AS_OF = "2026-08-15T12:00:00Z"
_TARGET_NAME = "Иванов"


def _open_window(
    tmp_path: Path, *, role: RoleCode = RoleCode.ADMINISTRATOR
) -> tuple[MainWindow, object, SessionState, dict[str, int]]:
    clock = lambda: _AS_OF  # noqa: E731
    db = tmp_path / "app.db"
    conn, admin, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, admin, clock=clock)
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")

    session: SessionState = admin
    if role is RoleCode.HR_EMPLOYEE:
        mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
        hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=role)
        session = SessionState(
            account_id=hr_id,
            login="hr1",
            role=role,
            master_key=admin.master_key,
        )
    elif role is RoleCode.OBSERVER:
        mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
        obs_id = mgr.create_account(login="obs1", password="ObsPass-1", role=role)
        session = SessionState(
            account_id=obs_id,
            login="obs1",
            role=role,
            master_key=admin.master_key,
        )

    window = MainWindow(conn=conn, session=session, db_path=db)
    return window, conn, session, ids


def _card_for(panel: RosterPanel, employee_id: int) -> EmployeeCardWidget:
    QApplication.processEvents()
    cards = [
        c
        for c in panel.findChildren(EmployeeCardWidget)
        if c._employee_id == employee_id
    ]
    assert cards, f"no card for employee {employee_id}"
    return cards[-1]


def _search_and_find_card(
    qtbot, window: MainWindow, employee_id: int
) -> tuple[RosterPanel, EmployeeCardWidget]:
    search = window.findChild(QLineEdit, "searchInput")
    assert search is not None and search.isEnabled()
    search.setText(_TARGET_NAME)
    panel = window.findChild(RosterPanel)
    assert panel is not None
    qtbot.waitUntil(
        lambda: any(
            c._employee_id == employee_id
            for c in panel.findChildren(EmployeeCardWidget)
        )
    )
    return panel, _card_for(panel, employee_id)


def _fill_status_assign_remote() -> None:
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, StatusAssignDialog) and widget.isVisible():
            status = widget.findChild(QComboBox, "statusAssignStatus")
            start = widget.findChild(QDateEdit, "statusAssignStart")
            save = widget.findChild(QPushButton, "statusAssignSaveBtn")
            assert status is not None and start is not None and save is not None
            idx = status.findData(2)  # Удалённо
            assert idx >= 0
            status.setCurrentIndex(idx)
            start.setDate(QDate.fromString("2026-08-15", "yyyy-MM-dd"))
            save.click()
            return
    raise AssertionError("StatusAssignDialog not visible")


def _assign_from_open_card() -> None:
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, EmployeeCardDialog) and widget.isVisible():
            btn = widget.findChild(QPushButton, "assignStatusFromCardBtn")
            assert btn is not None and btn.isEnabled()
            QTimer.singleShot(0, _fill_status_assign_remote)
            btn.click()
            return
    raise AssertionError("EmployeeCardDialog not visible")


def _open_card_from_popup() -> None:
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, EmployeePopupDialog) and widget.isVisible():
            btn = widget.findChild(QAbstractButton, "openEmployeeCard")
            assert btn is not None
            QTimer.singleShot(0, _assign_from_open_card)
            btn.click()
            return
    raise AssertionError("EmployeePopupDialog not visible")


def _assert_view_only_on_popup_then_card() -> None:
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, EmployeePopupDialog) and widget.isVisible():
            assert widget.findChild(QAbstractButton, "assignStatusBtn") is None
            card_btn = widget.findChild(QAbstractButton, "openEmployeeCard")
            assert card_btn is not None

            def _check_card() -> None:
                for inner in QApplication.topLevelWidgets():
                    if isinstance(inner, EmployeeCardDialog) and inner.isVisible():
                        assert (
                            inner.findChild(QPushButton, "assignStatusFromCardBtn")
                            is None
                        )
                        inner.reject()
                        return
                raise AssertionError("EmployeeCardDialog not visible")

            QTimer.singleShot(0, _check_card)
            card_btn.click()
            return
    raise AssertionError("EmployeePopupDialog not visible")


@pytest.mark.acceptance
@pytest.mark.parametrize("role", [RoleCode.ADMINISTRATOR, RoleCode.HR_EMPLOYEE])
def test_search_open_card_assign_status_updates_roster(
    qtbot, tmp_path: Path, role: RoleCode
) -> None:
    """ТЗ §11 / TESTING §5.2 item 2: поиск → карточка → смена статуса (Admin/HR)."""
    window, conn, _session, ids = _open_window(tmp_path, role=role)
    qtbot.addWidget(window)
    emp_id = ids["employee_a_id"]
    panel, card = _search_and_find_card(qtbot, window, emp_id)

    before = next(r for r in panel._all_rows if r.employee_id == emp_id)
    assert before.status_id == 1

    QTimer.singleShot(0, _open_card_from_popup)
    card.clicked.emit(emp_id)

    qtbot.waitUntil(
        lambda: next(r for r in panel._all_rows if r.employee_id == emp_id).status_id
        == 2
    )
    after = next(r for r in panel._all_rows if r.employee_id == emp_id)
    assert after.status_name == "Удалённо"
    labels = [lbl.text() for lbl in _card_for(panel, emp_id).findChildren(QLabel)]
    assert "Удалённо" in labels

    window.close()
    conn.close()


@pytest.mark.acceptance
def test_observer_search_and_card_are_view_only(qtbot, tmp_path: Path) -> None:
    """ТЗ §11 / TESTING §5.2 item 2: Наблюдатель — поиск и карточка без назначения."""
    window, conn, _session, ids = _open_window(tmp_path, role=RoleCode.OBSERVER)
    qtbot.addWidget(window)
    emp_id = ids["employee_a_id"]
    panel, card = _search_and_find_card(qtbot, window, emp_id)

    QTimer.singleShot(0, _assert_view_only_on_popup_then_card)
    card.clicked.emit(emp_id)

    still = next(r for r in panel._all_rows if r.employee_id == emp_id)
    assert still.status_id == 1

    window.close()
    conn.close()
