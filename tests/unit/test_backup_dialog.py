"""UI: диалог резервного копирования — права, создание, восстановление (EPIC-012)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QMessageBox, QPushButton

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.backup import BackupService
from services.bootstrap import BootstrapService
from services.session import SessionState
from tests.fixtures.synthetic import seed_synthetic_org
from ui.backup_dialog import BackupDialog


def _open(tmp_path: Path):
    clock = lambda: "2026-08-30T15:00:00Z"  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    seed_synthetic_org(conn)
    backup = BackupService(conn, session, db_path=db, clock=clock)
    return db, conn, session, backup, clock


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


def _message_box_returns(
    monkeypatch: pytest.MonkeyPatch,
    *,
    warning: QMessageBox.StandardButton | None = None,
) -> dict[str, list[tuple[object, ...]]]:
    seen: dict[str, list[tuple[object, ...]]] = {"warning": [], "critical": [], "information": []}

    if warning is not None:

        def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
            seen["warning"].append(args)
            return warning

        monkeypatch.setattr(QMessageBox, "warning", _warning)

    def _critical(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen["critical"].append(args)
        return QMessageBox.StandardButton.Ok

    def _information(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen["information"].append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", _critical)
    monkeypatch.setattr(QMessageBox, "information", _information)
    return seen


def test_backup_buttons_follow_role_permissions(qtbot, tmp_path: Path) -> None:
    db, conn, admin, backup, clock = _open(tmp_path)
    admin_dialog = BackupDialog(backup, admin)
    qtbot.addWidget(admin_dialog)
    assert admin_dialog.findChild(QPushButton, "backupCreateBtn").isEnabled()
    assert admin_dialog.findChild(QPushButton, "backupRestoreBtn").isEnabled()

    hr = _hr_session(conn, admin, db, clock)
    hr_dialog = BackupDialog(BackupService(conn, hr, db_path=db, clock=clock), hr)
    qtbot.addWidget(hr_dialog)
    assert hr_dialog.findChild(QPushButton, "backupCreateBtn").isEnabled()
    assert not hr_dialog.findChild(QPushButton, "backupRestoreBtn").isEnabled()

    obs = _observer_session(conn, admin, db, clock)
    obs_dialog = BackupDialog(BackupService(conn, obs, db_path=db, clock=clock), obs)
    qtbot.addWidget(obs_dialog)
    assert not obs_dialog.findChild(QPushButton, "backupCreateBtn").isEnabled()
    assert not obs_dialog.findChild(QPushButton, "backupRestoreBtn").isEnabled()
    conn.close()


def test_create_backup_happy_path(qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db, conn, session, backup, _clock = _open(tmp_path)
    dest = tmp_path / "backups"
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(dest),
    )
    dialog = BackupDialog(backup, session)
    qtbot.addWidget(dialog)
    create_btn = dialog.findChild(QPushButton, "backupCreateBtn")
    status = dialog.findChild(QLabel, "backupStatus")
    assert create_btn is not None and status is not None

    qtbot.mouseClick(create_btn, Qt.MouseButton.LeftButton)

    assert list(dest.glob("*.db"))
    assert status.text().startswith("Создано:")
    conn.close()


def test_create_backup_cancelled_when_directory_not_chosen(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _db, conn, session, backup, _clock = _open(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args, **_kwargs: "")
    dialog = BackupDialog(backup, session)
    qtbot.addWidget(dialog)
    create_btn = dialog.findChild(QPushButton, "backupCreateBtn")
    status = dialog.findChild(QLabel, "backupStatus")
    assert create_btn is not None and status is not None

    qtbot.mouseClick(create_btn, Qt.MouseButton.LeftButton)

    assert status.text() == ""
    assert not list(dest.glob("*.db"))
    conn.close()


def test_restore_happy_path_calls_callback_and_accepts(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, conn, session, backup, _clock = _open(tmp_path)
    snapshot = backup.create_backup(tmp_path / "snap")
    restored: list[object] = []
    _message_box_returns(monkeypatch, warning=QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(snapshot), "*.db"),
    )
    dialog = BackupDialog(backup, session, on_restored=restored.append)
    qtbot.addWidget(dialog)
    dialog._restore()

    assert restored
    assert dialog.result() == QDialog.DialogCode.Accepted
    conn2 = restored[0]
    row = conn2.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    assert row >= 2
    conn2.close()
    conn.close()


def test_restore_cancelled_when_user_declines_confirmation(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _db, conn, session, backup, _clock = _open(tmp_path)
    snapshot = backup.create_backup(tmp_path / "snap")
    restored: list[object] = []
    restore_calls: list[object] = []
    original_restore = backup.restore_backup

    def tracking_restore(path: Path):
        restore_calls.append(path)
        return original_restore(path)

    monkeypatch.setattr(backup, "restore_backup", tracking_restore)
    _message_box_returns(monkeypatch, warning=QMessageBox.StandardButton.No)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(snapshot), "*.db"),
    )
    dialog = BackupDialog(backup, session, on_restored=restored.append)
    qtbot.addWidget(dialog)
    dialog._restore()

    assert not restored
    assert not restore_calls
    assert dialog.result() != QDialog.DialogCode.Accepted
    conn.close()


def test_restore_failure_shows_critical_and_skips_callback(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _db, conn, session, backup, _clock = _open(tmp_path)
    bad_path = tmp_path / "missing.db"
    restored: list[object] = []
    seen = _message_box_returns(monkeypatch, warning=QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(bad_path), "*.db"),
    )
    dialog = BackupDialog(backup, session, on_restored=restored.append)
    qtbot.addWidget(dialog)
    dialog._restore()

    assert seen["critical"]
    assert not restored
    assert dialog.result() != QDialog.DialogCode.Accepted
    conn.close()
