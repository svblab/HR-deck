"""UI: диалог назначения статуса (EPIC-006 gap)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QComboBox, QDateEdit, QMessageBox, QPushButton

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.availability_statuses import AvailabilityStatusService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.status_assign_dialog import StatusAssignDialog


def _open(tmp_path: Path, *, as_of: str = "2026-08-15T12:00:00Z"):
    clock = lambda: as_of  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=clock)
    statuses = AvailabilityStatusService(conn, session, clock=clock)
    return db, conn, session, history, statuses, ids, clock


def _observer(conn, admin: SessionState, db: Path, clock) -> SessionState:  # noqa: ANN001
    mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
    obs_id = mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    return SessionState(
        account_id=obs_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=admin.master_key,
    )


def test_assign_office_after_expired_vacation(qtbot, tmp_path: Path) -> None:
    _db, conn, session, history, statuses, ids, _clock = _open(tmp_path)
    emp = ids["employee_a_id"]
    history.assign_status(
        emp, status_id=5, start_date="2026-08-01", end_date="2026-08-10"
    )
    assert history.current_status(emp, as_of="2026-08-15") is None

    dialog = StatusAssignDialog(
        history,
        statuses,
        session,
        employee_id=emp,
        employee_name="A",
    )
    qtbot.addWidget(dialog)
    status_combo = dialog.findChild(QComboBox, "statusAssignStatus")
    start = dialog.findChild(QDateEdit, "statusAssignStart")
    save = dialog.findChild(QPushButton, "statusAssignSaveBtn")
    assert status_combo is not None and start is not None and save is not None

    idx = status_combo.findData(1)
    assert idx >= 0
    status_combo.setCurrentIndex(idx)
    start.setDate(QDate.fromString("2026-08-15", "yyyy-MM-dd"))
    qtbot.mouseClick(save, Qt.MouseButton.LeftButton)

    assert dialog.result() == dialog.DialogCode.Accepted
    current = history.current_status(emp, as_of="2026-08-15")
    assert current is not None and current.status_id == 1
    conn.close()


def test_observer_cannot_save(qtbot, tmp_path: Path) -> None:
    db, conn, admin, history, statuses, ids, clock = _open(tmp_path)
    obs = _observer(conn, admin, db, clock)
    dialog = StatusAssignDialog(
        StatusHistoryService(conn, obs, clock=clock),
        AvailabilityStatusService(conn, obs, clock=clock),
        obs,
        employee_id=ids["employee_a_id"],
        employee_name="A",
    )
    qtbot.addWidget(dialog)
    save = dialog.findChild(QPushButton, "statusAssignSaveBtn")
    assert save is not None
    assert not save.isEnabled()
    conn.close()


def test_confirmation_required_then_accept(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _db, conn, session, history, statuses, ids, _clock = _open(
        tmp_path, as_of="2026-08-01T12:00:00Z"
    )
    emp = ids["employee_a_id"]
    history.assign_status(
        emp, status_id=1, start_date="2026-08-01", end_date="2026-08-31"
    )

    seen: list[object] = []

    def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen.append(args)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "warning", _warning)

    dialog = StatusAssignDialog(
        history,
        statuses,
        session,
        employee_id=emp,
        employee_name="A",
    )
    qtbot.addWidget(dialog)
    status_combo = dialog.findChild(QComboBox, "statusAssignStatus")
    start = dialog.findChild(QDateEdit, "statusAssignStart")
    end = dialog.findChild(QDateEdit, "statusAssignEnd")
    end_mode = dialog.findChild(QComboBox, "statusAssignEndMode")
    save = dialog.findChild(QPushButton, "statusAssignSaveBtn")
    assert status_combo is not None and start is not None and end is not None
    assert end_mode is not None and save is not None

    # Sick leave (policy requires end) overlapping office → confirmation
    idx = status_combo.findData(4)
    assert idx >= 0
    status_combo.setCurrentIndex(idx)
    start.setDate(QDate.fromString("2026-08-10", "yyyy-MM-dd"))
    end_mode.setCurrentIndex(1)
    end.setDate(QDate.fromString("2026-08-12", "yyyy-MM-dd"))
    qtbot.mouseClick(save, Qt.MouseButton.LeftButton)

    assert seen
    assert dialog.result() == dialog.DialogCode.Accepted
    conn.close()
