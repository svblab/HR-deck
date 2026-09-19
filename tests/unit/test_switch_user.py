"""UI acceptance: switch user without restarting the application."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from unittest.mock import patch

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QToolButton

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationService
from services.bootstrap import BootstrapService
from ui.auth_dialogs import AccountsDialog, LoginDialog
from ui.main_window import MainWindow
from ui.roster_panel import RosterPanel


def _seed_accounts(tmp_path: Path) -> Path:
    db = tmp_path / "app.db"
    clock = lambda: "2026-09-12T10:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    mgr = AccountManagementService(conn, session, db_path=db, clock=clock)
    mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    conn.close()
    return db


def _open_window(
    qtbot,
    tmp_path: Path,
    *,
    login: str,
    password: str,
) -> tuple[MainWindow, AuthenticationService]:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login=login, password=password)
    window = MainWindow(conn=conn, session=session, db_path=db)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window, auth


def _switch_btn(window: MainWindow) -> QToolButton:
    btn = window.findChild(QToolButton, "switchUserBtn")
    assert btn is not None
    return btn


@pytest.mark.acceptance
def test_switch_user_first_bind_emits_no_disconnect_warning(
    qtbot, tmp_path: Path, recwarn
) -> None:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="admin", password="AdminPass-1")
    window = MainWindow(db_path=db)
    qtbot.addWidget(window)
    window._bind_session(conn, session)
    assert not any(
        "Failed to disconnect" in str(w.message) for w in recwarn.list
    )
    window.close()
    conn.close()


@pytest.mark.acceptance
def test_startup_with_session_builds_single_roster_no_placeholder(
    qtbot, tmp_path: Path
) -> None:
    window, _auth = _open_window(qtbot, tmp_path, login="admin", password="AdminPass-1")
    assert window.findChild(QLabel, "contentPlaceholder") is None
    assert window.findChild(QPushButton, "primaryBtn") is None
    assert len(window.findChildren(RosterPanel)) == 1
    window.close()
    if window._conn is not None:
        window._conn.close()


@pytest.mark.acceptance
@pytest.mark.parametrize(
    ("login", "password"),
    [
        ("admin", "AdminPass-1"),
        ("hr1", "HrPass-1"),
        ("obs1", "ObsPass-1"),
    ],
)
def test_switch_user_action_visible_for_all_roles(
    qtbot, tmp_path: Path, login: str, password: str
) -> None:
    window, _auth = _open_window(qtbot, tmp_path, login=login, password=password)
    btn = _switch_btn(window)
    assert btn.isVisible()
    assert btn.isEnabled()
    window.close()
    if window._conn is not None:
        window._conn.close()


@pytest.mark.acceptance
def test_switch_user_returns_to_login_without_process_exit(qtbot, tmp_path: Path) -> None:
    window, auth = _open_window(qtbot, tmp_path, login="admin", password="AdminPass-1")
    seen_login: list[LoginDialog] = []

    def _relogin() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, LoginDialog) and widget.isVisible():
                seen_login.append(widget)
                widget._auth = auth
                widget._login.setText("hr1")
                widget._password.setText("HrPass-1")
                widget._submit()
                return
        raise AssertionError("LoginDialog not visible")

    QTimer.singleShot(0, _relogin)
    assert window.switch_user() is True

    assert len(seen_login) == 1
    assert window.isVisible()
    assert window._session is not None
    assert window._session.login == "hr1"
    window.close()
    window._conn.close()


@pytest.mark.acceptance
def test_switch_user_clears_previous_session_secrets(qtbot, tmp_path: Path) -> None:
    window, auth = _open_window(qtbot, tmp_path, login="admin", password="AdminPass-1")
    old_session = window._session
    assert old_session is not None
    assert old_session.master_key != b""

    def _relogin() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, LoginDialog) and widget.isVisible():
                widget._auth = auth
                widget._login.setText("obs1")
                widget._password.setText("ObsPass-1")
                widget._submit()
                return

    QTimer.singleShot(0, _relogin)
    assert window.switch_user() is True

    assert old_session.master_key == b""
    assert window._session is not old_session
    window.close()
    window._conn.close()


@pytest.mark.acceptance
def test_switch_user_then_login_as_different_role(qtbot, tmp_path: Path) -> None:
    window, auth = _open_window(qtbot, tmp_path, login="admin", password="AdminPass-1")
    assert window._accounts_btn is not None
    assert window._accounts_btn.isEnabled()

    def _relogin() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, LoginDialog) and widget.isVisible():
                widget._auth = auth
                widget._login.setText("hr1")
                widget._password.setText("HrPass-1")
                widget._submit()
                return

    QTimer.singleShot(0, _relogin)
    assert window.switch_user() is True

    assert window._session is not None
    assert window._session.login == "hr1"
    assert window._session.role is RoleCode.HR_EMPLOYEE
    assert window._accounts_btn is not None
    assert not window._accounts_btn.isEnabled()
    assert not window._accounts_btn.isVisible()
    window.close()
    window._conn.close()


@pytest.mark.acceptance
def test_switch_user_cancel_preserves_session_and_roster(qtbot, tmp_path: Path) -> None:
    window, _auth = _open_window(qtbot, tmp_path, login="admin", password="AdminPass-1")
    old_conn = window._conn
    old_session = window._session
    roster = window.findChild(RosterPanel)
    assert roster is not None
    assert old_conn is not None and old_session is not None

    def _cancel() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, LoginDialog) and widget.isVisible():
                widget.reject()
                return
        raise AssertionError("LoginDialog not visible")

    QTimer.singleShot(0, _cancel)
    window._switch_user()

    assert window.isVisible()
    assert window._conn is old_conn
    assert window._session is old_session
    assert window._session.login == "admin"
    assert window.findChild(RosterPanel) is roster
    assert _switch_btn(window).isEnabled()
    window.close()
    window._conn.close()


@pytest.mark.acceptance
def test_switch_user_cancel_does_not_call_logout(qtbot, tmp_path: Path) -> None:
    window, _auth = _open_window(qtbot, tmp_path, login="admin", password="AdminPass-1")

    def _cancel() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, LoginDialog) and widget.isVisible():
                widget.reject()
                return
        raise AssertionError("LoginDialog not visible")

    with patch.object(window._auth, "logout") as logout_mock:
        QTimer.singleShot(0, _cancel)
        assert window.switch_user() is False
        logout_mock.assert_not_called()

    window.close()
    if window._conn is not None:
        window._conn.close()


@pytest.mark.acceptance
def test_login_dialog_second_connection_while_main_window_connection_open(
    qtbot, tmp_path: Path
) -> None:
    """LoginDialog.login() opens its own SQLCipher connection; must not lock the DB."""
    window, auth = _open_window(qtbot, tmp_path, login="admin", password="AdminPass-1")
    assert window._conn is not None
    db = window._db_path
    assert db is not None

    login = LoginDialog(db, window)
    qtbot.addWidget(login)
    login._auth = auth
    login._login.setText("hr1")
    login._password.setText("HrPass-1")
    login._submit()

    assert login.conn is not None
    assert login.session is not None
    assert login.session.login == "hr1"
    assert window._conn is not None
    login.conn.close()
    window.close()
    window._conn.close()


@pytest.mark.acceptance
def test_switch_user_resets_inactivity_timer(qtbot, tmp_path: Path) -> None:
    window, auth = _open_window(qtbot, tmp_path, login="admin", password="AdminPass-1")
    assert window._session is not None
    window._session.last_activity_mono = 1_000.0
    window._session.inactivity_timeout_seconds = 60
    assert window._session.check_inactivity(1_070.0)
    assert window._session.locked

    def _relogin() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, LoginDialog) and widget.isVisible():
                widget._auth = auth
                widget._login.setText("hr1")
                widget._password.setText("HrPass-1")
                widget._submit()
                return

    QTimer.singleShot(0, _relogin)
    assert window.switch_user() is True
    assert window._session is not None
    assert not window._session.locked
    assert window._session.last_activity_mono >= monotonic() - 2.0
    window.close()
    window._conn.close()


@pytest.mark.acceptance
def test_switch_user_closes_open_dialogs(qtbot, tmp_path: Path) -> None:
    window, auth = _open_window(qtbot, tmp_path, login="admin", password="AdminPass-1")
    assert window._conn is not None and window._session is not None
    accounts = AccountsDialog(
        AccountManagementService(window._conn, window._session, db_path=window._db_path),
        window,
    )
    qtbot.addWidget(accounts)
    accounts.open()
    assert accounts.isVisible()

    def _relogin() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, LoginDialog) and widget.isVisible():
                widget._auth = auth
                widget._login.setText("hr1")
                widget._password.setText("HrPass-1")
                widget._submit()
                return

    QTimer.singleShot(0, _relogin)
    assert window.switch_user() is True

    assert not accounts.isVisible()
    open_dialogs = [
        w
        for w in QApplication.topLevelWidgets()
        if isinstance(w, QDialog) and w.isVisible()
    ]
    assert open_dialogs == []
    window.close()
    window._conn.close()
