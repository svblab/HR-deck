"""Unit: диалог библиотеки шаблонов — видимость кнопок по RBAC и ошибки загрузки."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from openpyxl import Workbook
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.branch_summary_report import BranchSummaryReportService
from services.directories import DirectoryService
from services.session import SessionState
from services.status_history import StatusHistoryService
from services.template_library import TemplateLibraryService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.template_library_dialog import TemplateLibraryDialog

_BRANCH_SUMMARY = (
    Path(__file__).resolve().parents[2] / "templates_samples" / "branch_summary_report.xlsx"
)


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


def _wired_dialog(tmp_path: Path) -> TemplateLibraryDialog:
    clock = lambda: "2026-08-15T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=clock)
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    library = TemplateLibraryService(conn, session, data_dir=tmp_path, clock=clock)
    source = tmp_path / "branch_summary.xlsx"
    shutil.copyfile(_BRANCH_SUMMARY, source)
    library.upload_version(name="Сводка", source=source)
    directories = DirectoryService(conn, session, clock=clock)
    branch_summary = BranchSummaryReportService(conn, session, clock=clock)
    dlg = TemplateLibraryDialog(
        library,
        session,
        branch_summary=branch_summary,
        directories=directories,
    )
    dlg._conn = conn  # type: ignore[attr-defined]
    dlg._seed_ids = ids  # type: ignore[attr-defined]
    dlg._reload_all()
    return dlg


def test_template_dialog_branch_summary_generate_passes_row_records(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dlg = _wired_dialog(tmp_path)
    qtbot.addWidget(dlg)
    out = tmp_path / "out.xlsx"
    captured: list[dict[str, object]] = []
    original = dlg._library.generate_report

    def _spy(version_id: int, output_path: Path, *, values=None, row_records=None):  # noqa: ANN001
        captured.append({"values": values, "row_records": row_records})
        return original(version_id, output_path, values=values or {}, row_records=row_records)

    monkeypatch.setattr(dlg._library, "generate_report", _spy)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(out), "*.xlsx"),
    )
    monkeypatch.setattr(
        "ui.template_library_dialog._prompt_branch_summary_params",
        lambda *_args, **_kwargs: (dlg._seed_ids["branch_id"], "2026-08-15"),  # type: ignore[attr-defined]
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    dlg._generate()

    assert captured
    assert captured[0]["row_records"]
    assert captured[0]["values"]
    assert captured[0]["values"]["report.branch_total"] == "2"
    dlg._conn.close()  # type: ignore[attr-defined]


def test_template_dialog_branch_summary_without_services_uses_empty_values(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = lambda: "2026-08-15T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    library = TemplateLibraryService(conn, session, data_dir=tmp_path, clock=clock)
    source = tmp_path / "branch_summary.xlsx"
    shutil.copyfile(_BRANCH_SUMMARY, source)
    library.upload_version(name="Сводка", source=source)
    dlg = TemplateLibraryDialog(library, session)
    qtbot.addWidget(dlg)
    dlg._reload_all()
    out = tmp_path / "out.xlsx"
    captured: list[dict[str, object]] = []
    original = dlg._library.generate_report

    def _spy(version_id: int, output_path: Path, *, values=None, row_records=None):  # noqa: ANN001
        captured.append({"values": values, "row_records": row_records})
        return original(version_id, output_path, values=values or {}, row_records=row_records)

    monkeypatch.setattr(dlg._library, "generate_report", _spy)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(out), "*.xlsx"),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    dlg._generate()

    assert captured
    assert captured[0]["values"] == {}
    assert captured[0]["row_records"] is None
    conn.close()
