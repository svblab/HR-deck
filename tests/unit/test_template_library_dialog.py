"""Unit: диалог библиотеки шаблонов — видимость кнопок по RBAC и ошибки загрузки."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

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


def _save_excel(path: Path, marker: str) -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet["A1"] = marker
    book.save(path)
    book.close()


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


def test_template_dialog_upload_validation_error_shows_message_box(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dlg = _dialog(tmp_path)
    qtbot.addWidget(dlg)
    bad = tmp_path / "bad.xlsx"
    _save_excel(bad, "{{неизвестный_маркер}}")

    seen: list[tuple[object, ...]] = []

    def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warning)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(bad), "*.xlsx"),
    )
    monkeypatch.setattr(
        "ui.template_library_dialog._prompt_text",
        lambda *_args, **_kwargs: ("Плохой шаблон", True),
    )

    dlg._upload()

    assert seen
    assert "неизвестный_маркер" in str(seen[0])
    dlg._conn.close()  # type: ignore[attr-defined]
