"""UI: conversion bulk review modal (EPIC-018 / Issue #124)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QMessageBox, QPushButton

from data.import_sessions import ImportSessionRepository
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employee_conversion import (
    ConversionBulkSaveItemResult,
    ConversionBulkSaveResult,
    EmployeeConversionService,
)
from services.employees import EmployeeService
from services.import_conversion_ingest import ImportConversionIngestResult
from tests.fixtures.synthetic import seed_synthetic_org
from ui.conversion_bulk_review_dialog import ConversionBulkReviewDialog
from ui.conversion_wizard_dialog import ConversionWizardDialog
from ui.conversion_wizard_flow import run_conversion_wizard_flow


def _open(tmp_path: Path):
    clock = lambda: "2026-09-25T10:00:00Z"  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=clock)
    directories = DirectoryService(conn, session, clock=clock)
    sessions = ImportSessionRepository(conn)
    conversion = EmployeeConversionService(
        conn, session, employees, sessions=sessions, db_path=db
    )
    return conn, session, employees, directories, sessions, conversion, ids, clock, db


def _stage(sessions, conn, rows: list[dict]) -> int:
    session_id = sessions.create_session(
        file_content_hash="e" * 64, last_accessed_at="2026-09-25T09:00:00Z"
    )
    for idx, values in enumerate(rows, start=2):
        sessions.insert_row(
            session_id=session_id,
            source_row_number=idx,
            values_json=json.dumps(values, ensure_ascii=False),
        )
    conn.commit()
    return session_id


def _ready_values(**overrides: str) -> dict[str, str]:
    base = {
        "full_name": "Новый Конверт",
        "branch": "Филиал Север (тест)",
        "department": "Департамент разработки",
        "division": "Отдел платформы",
        "position": "Инженер",
        "employment_type": "Штатный",
    }
    base.update(overrides)
    return base


@pytest.mark.acceptance
def test_bulk_dialog_ready_rows_checked_and_enabled(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, sessions, conversion, _ids, clock, _db = _open(
        tmp_path
    )
    session_id = _stage(
        sessions,
        conn,
        [
            _ready_values(),
            _ready_values(full_name="Иванов Иван Иванович"),
        ],
    )
    dialog = ConversionBulkReviewDialog(
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        employees=employees,
        directories=directories,
        clock=clock,
    )
    qtbot.addWidget(dialog)
    checks = dialog.findChildren(QCheckBox, "conversionBulkReviewRowCheck")
    assert len(checks) == 2
    assert checks[0].isEnabled() and checks[0].isChecked()
    assert not checks[1].isEnabled() and not checks[1].isChecked()
    conn.close()


@pytest.mark.acceptance
def test_apply_selected_invokes_bulk_save(qtbot, tmp_path: Path, monkeypatch) -> None:
    conn, session, employees, directories, sessions, conversion, _ids, clock, _db = _open(
        tmp_path
    )
    session_id = _stage(sessions, conn, [_ready_values()])
    dialog = ConversionBulkReviewDialog(
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        employees=employees,
        directories=directories,
        clock=clock,
    )
    qtbot.addWidget(dialog)
    captured: list[int] = []

    def _bulk(**kwargs):
        captured.extend(row_id for row_id, _data in kwargs["resolved_rows"])
        return ConversionBulkSaveResult(
            results=(ConversionBulkSaveItemResult(row_id=captured[0], employee_id=99),)
        )

    monkeypatch.setattr(conversion, "save_rows_bulk", _bulk)
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok
    )
    apply_btn = dialog.findChild(QPushButton, "conversionBulkReviewApplyBtn")
    assert apply_btn is not None
    qtbot.mouseClick(apply_btn, Qt.MouseButton.LeftButton)
    assert captured
    conn.close()


@pytest.mark.acceptance
def test_flow_shows_bulk_then_wizard(qtbot, tmp_path: Path, monkeypatch) -> None:
    conn, session, employees, directories, sessions, conversion, _ids, clock, db = _open(
        tmp_path
    )
    session_id = _stage(
        sessions,
        conn,
        [
            _ready_values(),
            _ready_values(full_name="Иванов Иван Иванович"),
        ],
    )
    ingest_mock = MagicMock()
    ingest_mock.ingest_file.return_value = ImportConversionIngestResult(
        session_id=session_id,
        file_content_hash="e" * 64,
        resumed=True,
        staged_row_count=2,
    )
    monkeypatch.setattr(
        "ui.conversion_wizard_flow.ImportConversionIngestService",
        lambda *args, **kwargs: ingest_mock,
    )
    monkeypatch.setattr(
        "ui.conversion_wizard_flow.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(tmp_path / "f.csv"), ""),
    )
    bulk_seen: list[bool] = []
    wizard_seen: list[bool] = []

    def _bulk_exec(self):
        bulk_seen.append(True)
        return QDialog.DialogCode.Accepted

    def _wizard_exec(self):
        wizard_seen.append(True)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ConversionBulkReviewDialog, "exec", _bulk_exec)
    monkeypatch.setattr(ConversionWizardDialog, "exec", _wizard_exec)

    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    run_conversion_wizard_flow(
        parent,
        conn,
        session,
        employees,
        directories,
        clock=clock,
        db_path=db,
    )
    assert bulk_seen
    assert wizard_seen
    conn.close()
