"""UI: предпросмотр импорта и потоки run_import_flow/run_export_flow (ТЗ §3.7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QWidget,
)

from domain.employee import EmployeeCreateInput
from domain.employee_import import ImportIssue, ImportPreview, ImportReadyRow
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employee_import import EmployeeImportService
from services.employees import EmployeeService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.import_export_dialog import ImportPreviewDialog, run_export_flow, run_import_flow


def _open(tmp_path: Path):
    clock = lambda: "2026-08-27T12:00:00Z"  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=clock)
    directories = DirectoryService(conn, session, clock=clock)
    return conn, session, employees, directories


def _capture_warnings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    seen: list[tuple[object, ...]] = []

    def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warning)
    return seen


def _sample_preview(*, with_ready: bool = True) -> ImportPreview:
    payload = EmployeeCreateInput(
        full_name="Кузнецова Ольга",
        position_id=1,
        branch_id=1,
        department_id=1,
        division_id=1,
        employment_type_id=1,
    )
    return ImportPreview(
        ready=(ImportReadyRow(5, payload, ()),) if with_ready else (),
        errors=(ImportIssue(3, "unknown branch"),),
        warnings=(ImportIssue(4, "possible duplicate", blocking=False),),
    )


def test_import_preview_dialog_lists_all_sections(qtbot) -> None:
    dialog = ImportPreviewDialog(_sample_preview())
    qtbot.addWidget(dialog)

    errors = dialog.findChild(QTableWidget, "importErrorTable")
    warnings = dialog.findChild(QTableWidget, "importWarningTable")
    ready = dialog.findChild(QTableWidget, "importReadyTable")
    summary = dialog.findChild(QLabel, "importPreviewSummary")
    confirm = dialog.findChild(QPushButton, "confirmImportBtn")
    assert errors is not None and warnings is not None and ready is not None
    assert summary is not None
    assert errors.rowCount() == 1
    assert warnings.rowCount() == 1
    assert ready.rowCount() == 1
    assert "К созданию: 1" in summary.text()
    assert confirm is not None and confirm.isEnabled()


def test_import_preview_dialog_without_ready_has_cancel_only(qtbot) -> None:
    dialog = ImportPreviewDialog(_sample_preview(with_ready=False))
    qtbot.addWidget(dialog)

    assert dialog.findChild(QPushButton, "confirmImportBtn") is None
    buttons = dialog.findChildren(QDialogButtonBox)
    assert len(buttons) == 1
    assert buttons[0].standardButtons() == QDialogButtonBox.StandardButton.Cancel


def test_run_import_flow_cancelled_when_file_not_chosen(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, session, employees, directories = _open(tmp_path)
    preview_calls: list[Path] = []
    original_preview = EmployeeImportService.preview_path

    def tracking_preview(self, path: Path):  # noqa: ANN001
        preview_calls.append(path)
        return original_preview(self, path)

    monkeypatch.setattr(EmployeeImportService, "preview_path", tracking_preview)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: ("", ""))
    parent = QWidget()
    qtbot.addWidget(parent)

    assert not run_import_flow(parent, employees, directories, session)
    assert not preview_calls
    conn.close()


def test_run_import_flow_warns_on_invalid_file(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, session, employees, directories = _open(tmp_path)
    warnings = _capture_warnings(monkeypatch)
    bad = tmp_path / "bad.csv"
    bad.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(bad), "*.csv"),
    )
    parent = QWidget()
    qtbot.addWidget(parent)

    assert not run_import_flow(parent, employees, directories, session)
    assert warnings
    conn.close()


def test_run_import_flow_happy_path_creates_employee(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, session, employees, directories = _open(tmp_path)
    csv_path = tmp_path / "in.csv"
    csv_path.write_text(
        "ФИО,Должность,Филиал,Департамент,Отдел,Тип занятости\n"
        "Кузнецова Ольга,Инженер,Филиал Север (тест),Департамент разработки,"
        "Отдел платформы,Штатный\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(csv_path), "*.csv"),
    )
    monkeypatch.setattr(
        ImportPreviewDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    parent = QWidget()
    qtbot.addWidget(parent)

    assert run_import_flow(parent, employees, directories, session)
    names = {card.full_name for card in employees.list_employees(active_only=True)}
    assert "Кузнецова Ольга" in names
    conn.close()


def test_run_export_flow_creates_xlsx_with_appended_extension(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, session, employees, directories = _open(tmp_path)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "out"), "*.xlsx"),
    )
    parent = QWidget()
    qtbot.addWidget(parent)

    run_export_flow(parent, employees, directories, session)
    assert (tmp_path / "out.xlsx").is_file()
    conn.close()


def test_run_export_flow_cancelled_when_path_not_chosen(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, session, employees, directories = _open(tmp_path)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: ("", ""))
    parent = QWidget()
    qtbot.addWidget(parent)

    run_export_flow(parent, employees, directories, session)
    assert not list(tmp_path.glob("*.xlsx"))
    conn.close()
