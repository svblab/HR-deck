"""UI acceptance: standard report Excel+PDF (EPIC-016 §4 checklist item 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QPushButton,
    QTableWidget,
)

from domain.permissions import RoleCode
from domain.reports import ReportKind
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.main_window import MainWindow
from ui.reports_dialog import ReportsDialog

_AS_OF = "2026-08-15T12:00:00Z"


def _open_window(
    tmp_path: Path, *, role: RoleCode
) -> tuple[MainWindow, object, SessionState]:
    clock = lambda: _AS_OF  # noqa: E731
    db = tmp_path / "app.db"
    conn, admin, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    StatusHistoryService(conn, admin, clock=clock).assign_status(
        ids["employee_a_id"], status_id=1, start_date="2026-08-01"
    )

    session: SessionState = admin
    if role is RoleCode.HR_EMPLOYEE:
        mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
        hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=role)
        session = SessionState(
            account_id=hr_id,
            login="hr1",
            role=role,
            master_key=admin.master_key,
        )
    elif role is RoleCode.OBSERVER:
        mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
        obs_id = mgr.create_account(login="obs1", password="ObsPass-1", role=role)
        session = SessionState(
            account_id=obs_id,
            login="obs1",
            role=role,
            master_key=admin.master_key,
        )

    return MainWindow(conn=conn, session=session, db_path=db), conn, session


def _kind_index(combo: QComboBox, kind: ReportKind) -> int:
    for index in range(combo.count()):
        if combo.itemData(index) == kind:
            return index
    raise AssertionError(f"missing report kind {kind}")


def _assert_xlsx(path: Path) -> None:
    assert path.is_file()
    data = path.read_bytes()
    assert len(data) > 64
    assert data[:2] == b"PK"  # Office Open XML zip


def _assert_pdf(path: Path) -> None:
    assert path.is_file()
    data = path.read_bytes()
    assert len(data) > 64
    assert data.startswith(b"%PDF")


@pytest.mark.acceptance
@pytest.mark.parametrize(
    "role",
    [RoleCode.ADMINISTRATOR, RoleCode.HR_EMPLOYEE, RoleCode.OBSERVER],
)
def test_main_window_standard_report_xlsx_and_pdf(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: RoleCode
) -> None:
    """ТЗ §11 / TESTING §2.3 + §5.2 item 3: Отчёты → SNAPSHOT → Excel + PDF."""
    window, conn, _session = _open_window(tmp_path, role=role)
    qtbot.addWidget(window)

    reports_btn = window.findChild(QPushButton, "reportsBtn")
    assert reports_btn is not None and reports_btn.isEnabled()

    xlsx_path = tmp_path / "snapshot.xlsx"
    pdf_path = tmp_path / "snapshot.pdf"
    save_queue = [(str(xlsx_path), "*.xlsx"), (str(pdf_path), "*.pdf")]

    def _save(_parent, _title, _default, _filt):  # noqa: ANN001
        assert save_queue, "unexpected extra save dialog"
        return save_queue.pop(0)

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save)

    def _drive_reports_dialog() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, ReportsDialog) and widget.isVisible():
                kind = widget.findChild(QComboBox, "reportKind")
                preview_btn = widget.findChild(QPushButton, "reportPreviewBtn")
                table = widget.findChild(QTableWidget, "reportPreviewTable")
                xlsx_btn = widget.findChild(QPushButton, "reportExportXlsx")
                pdf_btn = widget.findChild(QPushButton, "reportExportPdf")
                assert kind is not None and preview_btn is not None
                assert table is not None and xlsx_btn is not None and pdf_btn is not None

                kind.setCurrentIndex(_kind_index(kind, ReportKind.SNAPSHOT))
                qtbot.mouseClick(preview_btn, Qt.MouseButton.LeftButton)
                assert table.rowCount() >= 1

                qtbot.mouseClick(xlsx_btn, Qt.MouseButton.LeftButton)
                qtbot.mouseClick(pdf_btn, Qt.MouseButton.LeftButton)
                widget.accept()
                return
        raise AssertionError("ReportsDialog not visible")

    QTimer.singleShot(0, _drive_reports_dialog)
    qtbot.mouseClick(reports_btn, Qt.MouseButton.LeftButton)

    _assert_xlsx(xlsx_path)
    _assert_pdf(pdf_path)
    assert not save_queue

    window.close()
    conn.close()
