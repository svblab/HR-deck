"""UI acceptance: template report generate (EPIC-016 §4 checklist item 4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QPushButton,
    QTableWidget,
)

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.template_library import TemplateLibraryService
from ui.main_window import MainWindow
from ui.template_library_dialog import TemplateLibraryDialog

_AS_OF = "2026-09-06T12:00:00Z"
_SAMPLES = Path(__file__).resolve().parents[2] / "templates_samples"
_EXCEL = _SAMPLES / "sample_report.xlsx"
_PDF = _SAMPLES / "sample_report.pdf"
_MANIFEST = _SAMPLES / "sample_report.regions.json"


def _assert_xlsx(path: Path) -> None:
    assert path.is_file()
    data = path.read_bytes()
    assert len(data) > 64
    assert data[:2] == b"PK"


def _assert_pdf(path: Path) -> None:
    assert path.is_file()
    data = path.read_bytes()
    assert len(data) > 64
    assert data.startswith(b"%PDF")


def _fail_on_warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
    raise AssertionError(f"unexpected QMessageBox.warning: {args}")


def _session_for_role(
    conn: object,
    admin: SessionState,
    db: Path,
    clock,  # noqa: ANN001
    role: RoleCode,
) -> SessionState:
    if role is RoleCode.ADMINISTRATOR:
        return admin
    mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
    if role is RoleCode.HR_EMPLOYEE:
        account_id = mgr.create_account(
            login="hr1", password="HrPass-1", role=role
        )
        login = "hr1"
    else:
        account_id = mgr.create_account(
            login="obs1", password="ObsPass-1", role=role
        )
        login = "obs1"
    return SessionState(
        account_id=account_id,
        login=login,
        role=role,
        master_key=admin.master_key,
    )


def _upload_samples(
    qtbot,
    tmp_path: Path,
    admin: SessionState,
    conn: object,
    clock,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = TemplateLibraryService(conn, admin, data_dir=tmp_path, clock=clock)
    dlg = TemplateLibraryDialog(library, admin)
    qtbot.addWidget(dlg)

    open_queue: list[tuple[str, str]] = [
        (str(_EXCEL), "*.xlsx"),
        (str(_PDF), "*.pdf"),
        (str(_MANIFEST), "*.json"),
    ]
    names = iter(["Sample Excel", "Sample PDF"])

    def _open(*_args: object, **_kwargs: object) -> tuple[str, str]:
        assert open_queue, "unexpected extra open dialog"
        return open_queue.pop(0)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", _open)
    monkeypatch.setattr(
        "ui.template_library_dialog._prompt_text",
        lambda *_a, **_k: (next(names), True),
    )
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)

    dlg._upload()
    dlg._upload()
    assert not open_queue
    assert dlg.findChild(QTableWidget, "templateLibraryTable").rowCount() == 2
    dlg.close()


def _select_template_by_format(dialog: TemplateLibraryDialog, fmt: str) -> None:
    table = dialog.findChild(QTableWidget, "templateLibraryTable")
    assert table is not None
    for row in range(table.rowCount()):
        item = table.item(row, 1)
        if item is not None and item.text() == fmt:
            table.selectRow(row)
            return
    raise AssertionError(f"template format {fmt!r} not in library table")


def _generate_selected(
    dialog: TemplateLibraryDialog,
    qtbot,
    target: Path,
) -> None:
    versions = dialog.findChild(QTableWidget, "templateVersionTable")
    assert versions is not None and versions.rowCount() >= 1
    versions.selectRow(versions.rowCount() - 1)
    btn = dialog.findChild(QPushButton, "templateGenerateBtn")
    assert btn is not None and btn.isEnabled()
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert target.is_file()


@pytest.mark.acceptance
@pytest.mark.parametrize(
    "role",
    [RoleCode.ADMINISTRATOR, RoleCode.HR_EMPLOYEE, RoleCode.OBSERVER],
)
def test_main_window_template_report_xlsx_and_pdf(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: RoleCode
) -> None:
    """ТЗ §11 / TESTING §2.4 + §5.2 item 4: Шаблоны → Сформировать Excel + PDF."""
    assert _EXCEL.is_file() and _PDF.is_file() and _MANIFEST.is_file()

    clock = lambda: _AS_OF  # noqa: E731
    db = tmp_path / "app.db"
    conn, admin, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    _upload_samples(qtbot, tmp_path, admin, conn, clock, monkeypatch)

    session = _session_for_role(conn, admin, db, clock, role)
    window = MainWindow(conn=conn, session=session, db_path=db)
    qtbot.addWidget(window)

    templates_btn = window.findChild(QPushButton, "templatesBtn")
    assert templates_btn is not None and templates_btn.isEnabled()

    xlsx_out = tmp_path / f"out-{role.value}.xlsx"
    pdf_out = tmp_path / f"out-{role.value}.pdf"
    save_queue = [(str(xlsx_out), "*.xlsx"), (str(pdf_out), "*.pdf")]
    info_seen: list[tuple[object, ...]] = []

    def _save(*_args: object, **_kwargs: object) -> tuple[str, str]:
        assert save_queue, "unexpected extra save dialog"
        return save_queue.pop(0)

    def _info(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        info_seen.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save)
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)
    monkeypatch.setattr(QMessageBox, "information", _info)

    def _drive_templates_dialog() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, TemplateLibraryDialog) and widget.isVisible():
                _select_template_by_format(widget, "excel")
                _generate_selected(widget, qtbot, xlsx_out)
                _select_template_by_format(widget, "pdf")
                _generate_selected(widget, qtbot, pdf_out)
                widget.accept()
                return
        raise AssertionError("TemplateLibraryDialog not visible")

    QTimer.singleShot(0, _drive_templates_dialog)
    qtbot.mouseClick(templates_btn, Qt.MouseButton.LeftButton)

    _assert_xlsx(xlsx_out)
    _assert_pdf(pdf_out)
    assert not save_queue
    assert len(info_seen) == 2
    assert all("Отчёт сохранён" in str(args) for args in info_seen)

    window.close()
    conn.close()
