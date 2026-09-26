"""UI: EPIC-021 unified database operations dialog shell."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QToolButton,
    QWidget,
)

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.backup import BackupService
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.session import SessionState
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.backup_dialog import BackupOperationsWidget
from ui.database_operations_dialog import (
    DatabaseOperationsDialog,
    can_open_database_operations,
    database_operations_tab_visibility,
)
from ui.main_window import MainWindow


def _open(tmp_path: Path):
    clock = lambda: "2026-09-26T10:00:00Z"  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    seed_synthetic_org(conn)
    status_history = StatusHistoryService(conn, session, clock=clock)
    employees = EmployeeService(conn, session, status_history=status_history, clock=clock)
    directories = DirectoryService(conn, session, clock=clock)
    backup = BackupService(conn, session, db_path=db, clock=clock)
    return db, conn, session, employees, directories, backup, status_history, clock


def _hr_session(conn, admin: SessionState, db: Path, clock) -> SessionState:  # noqa: ANN001
    mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    return SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin.master_key,
    )


def _observer_session(conn, admin: SessionState, db: Path, clock) -> SessionState:  # noqa: ANN001
    mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
    obs_id = mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    return SessionState(
        account_id=obs_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=admin.master_key,
    )


def _dialog(
    conn,
    session,
    *,
    employees,
    directories,
    backup,
    status_history,
) -> DatabaseOperationsDialog:
    return DatabaseOperationsDialog(
        conn,
        session,
        backup=backup,
        employees=employees,
        directories=directories,
        status_history=status_history,
    )


def _tab_titles(tabs: QTabWidget) -> list[str]:
    return [tabs.tabText(i) for i in range(tabs.count())]


def test_can_open_database_operations_by_role() -> None:
    assert can_open_database_operations(
        SessionState(account_id=1, login="a", role=RoleCode.ADMINISTRATOR, master_key=b"x")
    )
    assert can_open_database_operations(
        SessionState(account_id=2, login="h", role=RoleCode.HR_EMPLOYEE, master_key=b"x")
    )
    assert not can_open_database_operations(
        SessionState(account_id=3, login="o", role=RoleCode.OBSERVER, master_key=b"x")
    )


def test_tab_visibility_helpers_match_roadmap() -> None:
    admin = SessionState(account_id=1, login="a", role=RoleCode.ADMINISTRATOR, master_key=b"x")
    hr = SessionState(account_id=2, login="h", role=RoleCode.HR_EMPLOYEE, master_key=b"x")
    assert database_operations_tab_visibility(admin) == {
        "conversion": True,
        "import": True,
        "backup": True,
    }
    assert database_operations_tab_visibility(hr) == {
        "conversion": True,
        "import": True,
        "backup": False,
    }


def test_dialog_tabs_by_role(qtbot, tmp_path: Path) -> None:
    db, conn, admin, employees, directories, backup, status_history, clock = _open(tmp_path)
    admin_dialog = _dialog(
        conn,
        admin,
        employees=employees,
        directories=directories,
        backup=backup,
        status_history=status_history,
    )
    qtbot.addWidget(admin_dialog)
    tabs = admin_dialog.findChild(QTabWidget, "databaseOperationsTabs")
    assert tabs is not None
    assert _tab_titles(tabs) == [
        "Конвертация данных",
        "Импорт данных",
        "Резервное копирование",
    ]

    hr = _hr_session(conn, admin, db, clock)
    hr_dialog = _dialog(
        conn,
        hr,
        employees=employees,
        directories=directories,
        backup=backup,
        status_history=status_history,
    )
    qtbot.addWidget(hr_dialog)
    hr_tabs = hr_dialog.findChild(QTabWidget, "databaseOperationsTabs")
    assert hr_tabs is not None
    assert _tab_titles(hr_tabs) == ["Конвертация данных", "Импорт данных"]
    assert hr_dialog.findChild(QWidget, "databaseOperationsBackupTab") is None
    conn.close()


def test_main_window_entry_hidden_for_observer(qtbot, tmp_path: Path) -> None:
    db, conn, admin, _e, _d, _b, _sh, clock = _open(tmp_path)
    obs = _observer_session(conn, admin, db, clock)
    window = MainWindow(conn=conn, session=obs, db_path=db)
    qtbot.addWidget(window)
    window.show()
    obs_btn = window.findChild(QToolButton, "databaseOperationsBtn")
    assert obs_btn is not None
    assert not obs_btn.isVisible()
    conn.close()


def test_main_window_entry_visible_for_hr_and_admin(qtbot, tmp_path: Path) -> None:
    db, conn, admin, _e, _d, _b, _sh, clock = _open(tmp_path)
    admin_window = MainWindow(conn=conn, session=admin, db_path=db)
    qtbot.addWidget(admin_window)
    admin_window.show()
    admin_btn = admin_window.findChild(QToolButton, "databaseOperationsBtn")
    assert admin_btn is not None and admin_btn.isVisible()

    hr = _hr_session(conn, admin, db, clock)
    hr_window = MainWindow(conn=conn, session=hr, db_path=db)
    qtbot.addWidget(hr_window)
    hr_window.show()
    hr_btn = hr_window.findChild(QToolButton, "databaseOperationsBtn")
    assert hr_btn is not None and hr_btn.isVisible()
    conn.close()


def test_backup_tab_preserves_role_button_permissions(qtbot, tmp_path: Path) -> None:
    db, conn, admin, employees, directories, backup, status_history, clock = _open(tmp_path)
    admin_dialog = _dialog(
        conn,
        admin,
        employees=employees,
        directories=directories,
        backup=backup,
        status_history=status_history,
    )
    qtbot.addWidget(admin_dialog)
    admin_panel = admin_dialog.findChild(BackupOperationsWidget, "backupOperationsWidget")
    assert admin_panel is not None
    assert admin_panel.findChild(QPushButton, "backupCreateBtn").isEnabled()
    assert admin_panel.findChild(QPushButton, "backupRestoreBtn").isEnabled()

    hr = _hr_session(conn, admin, db, clock)
    hr_backup = BackupService(conn, hr, db_path=db, clock=clock)
    hr_dialog = _dialog(
        conn,
        hr,
        employees=EmployeeService(conn, hr, clock=clock),
        directories=DirectoryService(conn, hr, clock=clock),
        backup=hr_backup,
        status_history=StatusHistoryService(conn, hr, clock=clock),
    )
    qtbot.addWidget(hr_dialog)
    assert hr_dialog.findChild(BackupOperationsWidget, "backupOperationsWidget") is None
    conn.close()


def test_backup_create_in_embedded_tab(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, conn, admin, employees, directories, backup, status_history, _clock = _open(tmp_path)
    dest = tmp_path / "backups"
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(dest),
    )
    dialog = _dialog(
        conn,
        admin,
        employees=employees,
        directories=directories,
        backup=backup,
        status_history=status_history,
    )
    qtbot.addWidget(dialog)
    panel = dialog.findChild(BackupOperationsWidget, "backupOperationsWidget")
    assert panel is not None
    create_btn = panel.findChild(QPushButton, "backupCreateBtn")
    status = panel.findChild(QLabel, "backupStatus")
    assert create_btn is not None and status is not None
    qtbot.mouseClick(create_btn, Qt.MouseButton.LeftButton)
    assert list(dest.glob("*.db"))
    assert status.text().startswith("Создано:")
    assert dialog.result() != QDialog.DialogCode.Accepted
    conn.close()


def test_backup_restore_in_tab_calls_callback_without_closing_shell(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, conn, admin, employees, directories, backup, status_history, _clock = _open(tmp_path)
    snapshot = backup.create_backup(tmp_path / "snap")
    restored: list[object] = []

    def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "warning", _warning)
    monkeypatch.setattr(QMessageBox, "information", lambda *_a, **_k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(snapshot), "*.db"),
    )
    dialog = DatabaseOperationsDialog(
        conn,
        admin,
        backup=backup,
        employees=employees,
        directories=directories,
        status_history=status_history,
        on_restored=restored.append,
    )
    qtbot.addWidget(dialog)
    panel = dialog.findChild(BackupOperationsWidget, "backupOperationsWidget")
    assert panel is not None
    panel._restore()
    assert restored
    assert dialog.result() != QDialog.DialogCode.Accepted
    restored[0].close()
    conn.close()
