"""UI: управление учётными записями — роль, архив, сброс пароля (EPIC-023)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QToolButton,
)

from domain.permissions import Permission, RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationError, AuthenticationService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from ui.auth_dialogs import AccountsDialog, _ResetPasswordDialog
from ui.main_window import MainWindow


def _seed_accounts(tmp_path: Path) -> Path:
    db = tmp_path / "app.db"
    clock = lambda: "2026-09-13T14:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    mgr = AccountManagementService(conn, session, db_path=db, clock=clock)
    mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    conn.close()
    return db


def _admin_service(
    tmp_path: Path,
) -> tuple[Path, object, AccountManagementService, AuthenticationService]:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="admin", password="AdminPass-1")
    service = AccountManagementService(conn, session, db_path=db)
    return db, conn, service, auth


def _account_id(service: AccountManagementService, login: str) -> int:
    return next(row.id for row in service.list_accounts() if row.login == login)


def test_accounts_dialog_shows_both_tabs_for_administrator(qtbot, tmp_path: Path) -> None:
    _db, conn, service, _auth = _admin_service(tmp_path)
    dlg = AccountsDialog(service)
    qtbot.addWidget(dlg)

    tabs = dlg.findChild(QTabWidget, "accountsTabs")
    assert tabs is not None
    assert tabs.count() == 2
    assert tabs.tabText(0) == "Учётные записи"
    assert tabs.tabText(1) == "Настройки безопасности"

    conn.close()  # type: ignore[union-attr]


def test_accounts_dialog_hides_security_tab_without_permission(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _db, conn, service, _auth = _admin_service(tmp_path)

    def _can(permission: Permission) -> bool:
        return permission != Permission.MANAGE_SECURITY_SETTINGS

    monkeypatch.setattr(service, "can", _can)

    dlg = AccountsDialog(service)
    qtbot.addWidget(dlg)

    tabs = dlg.findChild(QTabWidget, "accountsTabs")
    assert tabs is not None
    assert tabs.count() == 1
    assert tabs.tabText(0) == "Учётные записи"

    conn.close()  # type: ignore[union-attr]


@pytest.mark.acceptance
def test_accounts_dialog_set_role_via_row_action(qtbot, tmp_path: Path) -> None:
    _db, conn, service, _auth = _admin_service(tmp_path)
    hr_id = _account_id(service, "hr1")
    dlg = AccountsDialog(service)
    qtbot.addWidget(dlg)

    combo = dlg.findChild(QComboBox, f"accountRoleCombo_{hr_id}")
    apply_btn = dlg.findChild(QPushButton, f"accountApplyRoleBtn_{hr_id}")
    assert combo is not None and apply_btn is not None
    combo.setCurrentIndex(combo.findData(RoleCode.OBSERVER.value))
    apply_btn.click()

    updated = next(row for row in service.list_accounts() if row.id == hr_id)
    assert updated.role_code == RoleCode.OBSERVER.value
    conn.close()  # type: ignore[union-attr]


@pytest.mark.acceptance
def test_accounts_dialog_archive_and_restore(qtbot, tmp_path: Path) -> None:
    _db, conn, service, _auth = _admin_service(tmp_path)
    hr_id = _account_id(service, "hr1")
    dlg = AccountsDialog(service)
    qtbot.addWidget(dlg)

    archive_btn = dlg.findChild(QPushButton, f"accountToggleActiveBtn_{hr_id}")
    assert archive_btn is not None
    assert archive_btn.text() == "Архивировать"
    archive_btn.click()
    qtbot.waitUntil(
        lambda: not next(row for row in service.list_accounts() if row.id == hr_id).is_active
    )

    restore_btn = dlg.findChild(QPushButton, f"accountToggleActiveBtn_{hr_id}")
    assert restore_btn is not None
    restore_btn.click()
    qtbot.waitUntil(
        lambda: next(row for row in service.list_accounts() if row.id == hr_id).is_active
    )

    restored = next(row for row in service.list_accounts() if row.id == hr_id)
    assert restored.is_active is True
    conn.close()  # type: ignore[union-attr]


@pytest.mark.acceptance
def test_accounts_dialog_reset_password(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, conn, service, auth = _admin_service(tmp_path)
    hr_id = _account_id(service, "hr1")
    dlg = AccountsDialog(service)
    qtbot.addWidget(dlg)

    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    def _fill_reset_dialog() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, _ResetPasswordDialog) and widget.isVisible():
                widget._password.setText("HrPass-2")
                widget.accept()
                return
        raise AssertionError("Reset password dialog not visible")

    reset_btn = dlg.findChild(QPushButton, f"accountResetPasswordBtn_{hr_id}")
    assert reset_btn is not None
    QTimer.singleShot(0, _fill_reset_dialog)
    reset_btn.click()

    conn.close()  # type: ignore[union-attr]
    auth2 = AuthenticationService(sleeper=lambda _s: None)
    c2, _session = auth2.login(db_path=db, login="hr1", password="HrPass-2")
    c2.close()
    with pytest.raises(AuthenticationError):
        auth2.login(db_path=db, login="hr1", password="HrPass-1")


@pytest.mark.acceptance
def test_non_admin_never_sees_account_management_controls(qtbot, tmp_path: Path) -> None:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, hr_session = auth.login(db_path=db, login="hr1", password="HrPass-1")
    hr_service = AccountManagementService(conn, hr_session, db_path=db)

    with pytest.raises(AuthorizationError):
        hr_service.list_accounts()

    window = MainWindow(conn=conn, session=hr_session, db_path=db)
    qtbot.addWidget(window)
    matching = [
        btn for btn in window.findChildren(QToolButton) if btn.toolTip() == "Учётные записи"
    ]
    assert len(matching) == 1
    assert matching[0].isHidden()

    window.close()
    conn.close()
