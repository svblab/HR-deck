"""UI acceptance: login + session unlock (EPIC-016 §4 checklist item 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from data.accounts import AccountRepository
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationService
from services.bootstrap import BootstrapService
from ui.auth_dialogs import AccountsDialog, LoginDialog, UnlockDialog
from ui.main_window import MainWindow


def _capture_warnings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    seen: list[tuple[object, ...]] = []

    def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warning)  # type: ignore[attr-defined]
    return seen


def _seed_accounts(tmp_path: Path) -> Path:
    db = tmp_path / "app.db"
    clock = lambda: "2026-09-05T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    mgr = AccountManagementService(conn, session, db_path=db, clock=clock)
    mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    conn.close()
    return db


@pytest.mark.acceptance
@pytest.mark.parametrize(
    ("login", "password", "role"),
    [
        ("admin", "AdminPass-1", RoleCode.ADMINISTRATOR),
        ("hr1", "HrPass-1", RoleCode.HR_EMPLOYEE),
        ("obs1", "ObsPass-1", RoleCode.OBSERVER),
    ],
)
def test_login_dialog_success_for_each_role(
    qtbot, tmp_path: Path, login: str, password: str, role: RoleCode
) -> None:
    db = _seed_accounts(tmp_path)
    dlg = LoginDialog(db)
    qtbot.addWidget(dlg)
    dlg._auth = AuthenticationService(sleeper=lambda _s: None)
    dlg._login.setText(login)
    dlg._password.setText(password)
    dlg._submit()

    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.session is not None
    assert dlg.session.login == login
    assert dlg.session.role == role
    assert dlg.conn is not None
    dlg.conn.close()


@pytest.mark.acceptance
def test_unlock_dialog_rejects_bad_password(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="admin", password="AdminPass-1")
    session.lock(clear_key=True)
    warnings = _capture_warnings(monkeypatch)

    dlg = UnlockDialog(session, db, conn=conn)
    qtbot.addWidget(dlg)
    dlg._auth = auth
    dlg._password.setText("wrong-password")
    dlg._submit()

    assert dlg.result() != QDialog.DialogCode.Accepted
    assert session.locked
    texts = " ".join(str(item) for item in warnings)
    assert "Неверный пароль." in texts
    assert "wrong-password" not in texts


@pytest.mark.acceptance
def test_unlock_dialog_accepts_correct_password(qtbot, tmp_path: Path) -> None:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="hr1", password="HrPass-1")
    original_key = session.master_key
    session.lock(clear_key=True)
    conn.close()

    dlg = UnlockDialog(session, db, conn=None)
    qtbot.addWidget(dlg)
    dlg._auth = auth
    dlg._password.setText("HrPass-1")
    dlg._submit()

    assert dlg.result() == QDialog.DialogCode.Accepted
    assert not session.locked
    assert session.master_key == original_key
    assert dlg.conn is not None
    dlg.conn.close()


@pytest.mark.acceptance
def test_accounts_dialog_create_account_from_role_combo(
    qtbot, tmp_path: Path,
) -> None:
    """QComboBox возвращает StrEnum как str — создание учётки не должно падать."""
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="admin", password="AdminPass-1")
    service = AccountManagementService(conn, session, db_path=db)

    dlg = AccountsDialog(service)
    qtbot.addWidget(dlg)
    dlg._login.setText("hr2")
    dlg._password.setText("HrPass-2")
    dlg._role.setCurrentIndex(dlg._role.findData(RoleCode.HR_EMPLOYEE.value))
    dlg._create()

    created = [row for row in service.list_accounts() if row.login == "hr2"]
    assert len(created) == 1
    assert created[0].role_code == RoleCode.HR_EMPLOYEE.value
    conn.close()


@pytest.mark.acceptance
def test_accounts_dialog_offers_only_hr_and_observer_roles(qtbot, tmp_path: Path) -> None:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="admin", password="AdminPass-1")
    service = AccountManagementService(conn, session, db_path=db)

    dlg = AccountsDialog(service)
    qtbot.addWidget(dlg)
    roles = {dlg._role.itemData(i) for i in range(dlg._role.count())}
    assert roles == {RoleCode.HR_EMPLOYEE.value, RoleCode.OBSERVER.value}
    conn.close()


@pytest.mark.acceptance
def test_accounts_dialog_delete_non_admin_account(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="admin", password="AdminPass-1")
    service = AccountManagementService(conn, session, db_path=db)
    hr_id = service.create_account(login="hr-del", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_a, **_k: QMessageBox.StandardButton.Yes,
    )

    dlg = AccountsDialog(service)
    qtbot.addWidget(dlg)
    for row in range(dlg._table.rowCount()):
        item = dlg._table.item(row, 0)
        assert item is not None
        if item.text() == str(hr_id):
            dlg._table.selectRow(row)
            break
    assert dlg._delete_btn.isEnabled()
    dlg._delete_selected()
    assert all(a.id != hr_id for a in service.list_accounts())
    assert AccountRepository(conn).get_by_id(hr_id) is None
    conn.close()


@pytest.mark.acceptance
def test_main_window_idle_lock_shows_overlay_then_unlock(qtbot, tmp_path: Path) -> None:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="admin", password="AdminPass-1")

    window = MainWindow(conn=conn, session=session, db_path=db)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    seen_overlay: list[bool] = []

    def _unlock() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, UnlockDialog) and widget.isVisible():
                overlay = window.findChild(QWidget, "sessionLockOverlay")
                seen_overlay.append(overlay is not None and overlay.isVisible())
                widget._auth = auth
                widget._password.setText("AdminPass-1")
                widget._submit()
                return

    session.lock(clear_key=True)
    QTimer.singleShot(0, _unlock)
    window._check_idle()

    assert seen_overlay == [True]
    assert not session.locked
    assert window._conn is not None
    overlay = window.findChild(QWidget, "sessionLockOverlay")
    assert overlay is not None
    assert not overlay.isVisible()
    assert window._roster is not None
    assert window._roster._directories._conn is window._conn
    window._roster._service.filter_branches()
    window._roster._directories.list_branches(active_only=True)
    window.close()
    window._conn.close()


@pytest.mark.acceptance
def test_main_window_idle_lock_cancel_closes_window(qtbot, tmp_path: Path) -> None:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="obs1", password="ObsPass-1")

    window = MainWindow(conn=conn, session=session, db_path=db)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    def _cancel() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, UnlockDialog) and widget.isVisible():
                widget.reject()
                return

    session.lock(clear_key=True)
    QTimer.singleShot(0, _cancel)
    window._check_idle()

    assert window.isHidden() or not window.isVisible()
