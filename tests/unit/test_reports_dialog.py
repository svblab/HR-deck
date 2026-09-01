"""UI: диалог стандартных отчётов — фильтры, предпросмотр, экспорт (ТЗ §3.8.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QMessageBox, QPushButton, QTableWidget

from domain.reports import ReportKind
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.standard_reports import StandardReportService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.reports_dialog import ReportsDialog


def _open(tmp_path: Path):
    clock = lambda: "2026-08-30T12:00:00Z"  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    seed_synthetic_org(conn)
    reports = StandardReportService(conn, session, clock=clock)
    directories = DirectoryService(conn, session, clock=clock)
    employees = EmployeeService(conn, session, clock=clock)
    return conn, reports, directories, employees


def _kind_index(combo: QComboBox, kind: ReportKind) -> int:
    for index in range(combo.count()):
        if combo.itemData(index) == kind:
            return index
    raise AssertionError(f"missing report kind {kind}")


def _capture_warnings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    seen: list[tuple[object, ...]] = []

    def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warning)
    return seen


def test_filter_combos_include_all_option_and_expected_counts(qtbot, tmp_path: Path) -> None:
    conn, reports, directories, employees = _open(tmp_path)
    dialog = ReportsDialog(reports, directories, employees)
    qtbot.addWidget(dialog)

    branch = dialog.findChild(QComboBox, "reportBranch")
    dept = dialog.findChild(QComboBox, "reportDept")
    status = dialog.findChild(QComboBox, "reportStatus")
    employment = dialog.findChild(QComboBox, "reportEmployment")
    employee = dialog.findChild(QComboBox, "reportEmployee")
    assert branch is not None and dept is not None and status is not None
    assert employment is not None and employee is not None

    assert branch.count() == 2
    assert dept.count() == 2
    assert status.count() == 8
    assert employment.count() == 4
    assert employee.count() == 3
    for combo in (branch, dept, status, employment, employee):
        assert combo.itemText(0) == "Все"
        assert combo.itemData(0) is None

    conn.close()


def test_sync_params_enables_employee_only_for_history_report(qtbot, tmp_path: Path) -> None:
    conn, reports, directories, employees = _open(tmp_path)
    dialog = ReportsDialog(reports, directories, employees)
    qtbot.addWidget(dialog)
    employee = dialog.findChild(QComboBox, "reportEmployee")
    assert employee is not None

    dialog._kind.setCurrentIndex(_kind_index(dialog._kind, ReportKind.HISTORY))
    assert employee.isEnabled()

    dialog._kind.setCurrentIndex(_kind_index(dialog._kind, ReportKind.SNAPSHOT))
    assert not employee.isEnabled()

    conn.close()


def test_preview_warns_when_employee_required_but_not_selected(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, reports, directories, employees = _open(tmp_path)
    build_calls: list[object] = []
    original_build = reports.build

    def tracking_build(kind, params):  # noqa: ANN001
        build_calls.append((kind, params))
        return original_build(kind, params)

    monkeypatch.setattr(reports, "build", tracking_build)
    warnings = _capture_warnings(monkeypatch)

    dialog = ReportsDialog(reports, directories, employees)
    qtbot.addWidget(dialog)
    dialog._kind.setCurrentIndex(_kind_index(dialog._kind, ReportKind.HISTORY))
    dialog._employee.setCurrentIndex(0)

    preview_btn = dialog.findChild(QPushButton, "reportPreviewBtn")
    assert preview_btn is not None
    qtbot.mouseClick(preview_btn, Qt.MouseButton.LeftButton)

    assert warnings
    assert "сотрудник" in str(warnings[0]).casefold()
    assert not build_calls
    conn.close()


def test_preview_fills_table_matching_service_result(qtbot, tmp_path: Path) -> None:
    conn, reports, directories, employees = _open(tmp_path)
    dialog = ReportsDialog(reports, directories, employees)
    qtbot.addWidget(dialog)
    dialog._kind.setCurrentIndex(_kind_index(dialog._kind, ReportKind.SNAPSHOT))

    preview_btn = dialog.findChild(QPushButton, "reportPreviewBtn")
    table = dialog.findChild(QTableWidget, "reportPreviewTable")
    assert preview_btn is not None and table is not None
    qtbot.mouseClick(preview_btn, Qt.MouseButton.LeftButton)

    expected = reports.build(ReportKind.SNAPSHOT, dialog._params())
    grouped = any(row.group_label for row in expected.rows)
    expected_cols = len(expected.columns) if not grouped else 1 + len(expected.columns)
    assert table.rowCount() == len(expected.rows)
    assert table.columnCount() == expected_cols
    conn.close()


def test_export_xlsx_creates_file(qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, reports, directories, employees = _open(tmp_path)
    dialog = ReportsDialog(reports, directories, employees)
    qtbot.addWidget(dialog)
    dialog._kind.setCurrentIndex(_kind_index(dialog._kind, ReportKind.SNAPSHOT))
    dialog._preview()

    target = tmp_path / "report.xlsx"

    def _save(_parent, _title, _default, _filt):  # noqa: ANN001
        return (str(target), "*.xlsx")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save)
    export_btn = dialog.findChild(QPushButton, "reportExportXlsx")
    assert export_btn is not None
    qtbot.mouseClick(export_btn, Qt.MouseButton.LeftButton)
    assert target.is_file()
    conn.close()


def test_export_pdf_creates_file(qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, reports, directories, employees = _open(tmp_path)
    dialog = ReportsDialog(reports, directories, employees)
    qtbot.addWidget(dialog)
    dialog._kind.setCurrentIndex(_kind_index(dialog._kind, ReportKind.SNAPSHOT))
    dialog._preview()

    target = tmp_path / "report.pdf"

    def _save(_parent, _title, _default, _filt):  # noqa: ANN001
        return (str(target), "*.pdf")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save)
    export_btn = dialog.findChild(QPushButton, "reportExportPdf")
    assert export_btn is not None
    qtbot.mouseClick(export_btn, Qt.MouseButton.LeftButton)
    assert target.is_file()
    conn.close()


def test_export_without_preview_triggers_build(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, reports, directories, employees = _open(tmp_path)
    dialog = ReportsDialog(reports, directories, employees)
    qtbot.addWidget(dialog)
    dialog._kind.setCurrentIndex(_kind_index(dialog._kind, ReportKind.SNAPSHOT))
    assert dialog._table is None

    target = tmp_path / "report.xlsx"

    def _save(_parent, _title, _default, _filt):  # noqa: ANN001
        return (str(target), "*.xlsx")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save)
    export_btn = dialog.findChild(QPushButton, "reportExportXlsx")
    assert export_btn is not None
    qtbot.mouseClick(export_btn, Qt.MouseButton.LeftButton)

    assert dialog._table is not None
    assert target.is_file()
    conn.close()
