"""Unit: диалог библиотеки шаблонов — видимость кнопок по RBAC."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.template_library import TemplateLibraryService
from ui.template_library_dialog import TemplateLibraryDialog


def _dialog(tmp_path: Path, role: RoleCode = RoleCode.ADMINISTRATOR) -> TemplateLibraryDialog:
    clock = lambda: "2026-08-30T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    if role != RoleCode.ADMINISTRATOR:
        mgr = AccountManagementService(
            conn, session, db_path=tmp_path / "app.db", clock=clock
        )
        login = "hr1" if role == RoleCode.HR_EMPLOYEE else "obs1"
        pwd = "HrPass-1" if role == RoleCode.HR_EMPLOYEE else "ObsPass-1"
        account_id = mgr.create_account(login=login, password=pwd, role=role)
        session = SessionState(
            account_id=account_id,
            login=login,
            role=role,
            master_key=session.master_key,
        )
    library = TemplateLibraryService(conn, session, data_dir=tmp_path, clock=clock)
    dlg = TemplateLibraryDialog(library, session)
    dlg._conn = conn  # type: ignore[attr-defined]
    return dlg


def test_template_dialog_manage_buttons_enabled_for_admin(qtbot, tmp_path: Path) -> None:
    dlg = _dialog(tmp_path)
    qtbot.addWidget(dlg)
    assert dlg.findChild(QPushButton, "templateUploadBtn").isEnabled()
    assert dlg.findChild(QPushButton, "templateArchiveBtn").isEnabled()
    assert dlg.findChild(QPushButton, "templateGenerateBtn").isEnabled()
    dlg._conn.close()  # type: ignore[attr-defined]


def test_template_dialog_manage_buttons_disabled_for_hr(qtbot, tmp_path: Path) -> None:
    dlg = _dialog(tmp_path, RoleCode.HR_EMPLOYEE)
    qtbot.addWidget(dlg)
    assert not dlg.findChild(QPushButton, "templateUploadBtn").isEnabled()
    assert not dlg.findChild(QPushButton, "templateArchiveBtn").isEnabled()
    assert dlg.findChild(QPushButton, "templateGenerateBtn").isEnabled()
    dlg._conn.close()  # type: ignore[attr-defined]
