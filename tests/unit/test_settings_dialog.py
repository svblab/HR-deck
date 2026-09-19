"""UI: настройки программы — безопасность и профиль компании."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox, QPushButton, QToolButton

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationService
from services.bootstrap import BootstrapService
from ui.auth_dialogs import SettingsDialog
from ui.main_window import MainWindow


def _seed_accounts(tmp_path: Path) -> Path:
    db = tmp_path / "app.db"
    clock = lambda: "2026-09-13T14:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    mgr = AccountManagementService(conn, session, db_path=db, clock=clock)
    mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    conn.close()
    return db


def _admin_service(
    tmp_path: Path,
) -> tuple[Path, object, AccountManagementService]:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, session = auth.login(db_path=db, login="admin", password="AdminPass-1")
    service = AccountManagementService(conn, session, db_path=db)
    return db, conn, service


def test_settings_dialog_loads_and_saves_security_settings(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _db, conn, service = _admin_service(tmp_path)
    dlg = SettingsDialog(service)
    qtbot.addWidget(dlg)

    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    dlg._timeout.setValue(300)
    dlg._timeout_enabled.setChecked(False)
    dlg._delay.setValue(7)
    dlg._delay_enabled.setChecked(False)
    save_btn = dlg.findChild(QPushButton, "settingsSecuritySaveBtn")
    assert save_btn is not None
    save_btn.click()

    got = service.get_security_settings()
    assert got == {
        "inactivity_timeout_seconds": 300,
        "inactivity_timeout_enabled": False,
        "login_failure_delay_seconds": 7,
        "login_failure_delay_enabled": False,
    }
    conn.close()  # type: ignore[union-attr]


def test_settings_dialog_company_profile_round_trip(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _db, conn, service = _admin_service(tmp_path)
    dlg = SettingsDialog(service)
    qtbot.addWidget(dlg)

    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    dlg._company_name.setText("ООО Тест")
    dlg._logo_path.setText(str(tmp_path / "logo.png"))
    save_btn = dlg.findChild(QPushButton, "settingsProfileSaveBtn")
    assert save_btn is not None
    save_btn.click()

    got = service.get_company_profile()
    assert got == {
        "company_name": "ООО Тест",
        "logo_path": str(tmp_path / "logo.png"),
    }

    dlg2 = SettingsDialog(service)
    qtbot.addWidget(dlg2)
    assert dlg2._company_name.text() == "ООО Тест"
    assert dlg2._logo_path.text() == str(tmp_path / "logo.png")
    conn.close()  # type: ignore[union-attr]


def test_program_settings_button_hidden_without_permission(qtbot, tmp_path: Path) -> None:
    db = _seed_accounts(tmp_path)
    auth = AuthenticationService(sleeper=lambda _s: None)
    conn, hr_session = auth.login(db_path=db, login="hr1", password="HrPass-1")

    window = MainWindow(conn=conn, session=hr_session, db_path=db)
    qtbot.addWidget(window)
    matching = [
        btn for btn in window.findChildren(QToolButton) if btn.toolTip() == "Настройки программы"
    ]
    assert len(matching) == 1
    assert matching[0].isHidden()

    window.close()
    conn.close()
