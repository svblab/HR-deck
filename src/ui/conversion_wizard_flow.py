"""EPIC-018 / Issue #124: conversion ingest → bulk review → row wizard (ADR-0012 addendum)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget

from data.db import Connection
from data.import_sessions import ImportSessionRepository
from services.directories import DirectoryService
from services.employee_conversion import EmployeeConversionService
from services.employees import EmployeeService
from services.import_conversion_ingest import (
    ImportConversionIngestError,
    ImportConversionIngestService,
)
from services.session import SessionState
from services.status_history import StatusHistoryService
from ui.conversion_bulk_review_dialog import (
    ConversionBulkReviewDialog,
    connect_bulk_review_checkbox_updates,
)
from ui.conversion_wizard_dialog import ConversionWizardDialog

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_conversion_wizard_flow(
    parent: QWidget,
    conn: Connection,
    session: SessionState,
    employees: EmployeeService,
    directories: DirectoryService,
    *,
    status_history: StatusHistoryService | None = None,
    clock: Clock | None = None,
    db_path: Path | str | None = None,
) -> bool:
    """Entry for EPIC-021 «Конвертация данных» with bulk apply gate (Issue #124)."""
    path, _filter = QFileDialog.getOpenFileName(
        parent,
        "Конвертация данных",
        "",
        "Таблицы (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv)",
    )
    if not path:
        return False
    tick: Clock = clock or _utc_now
    ingest = ImportConversionIngestService(conn, session, clock=tick)
    sessions = ImportSessionRepository(conn)
    try:
        result = ingest.ingest_file(path)
    except ImportConversionIngestError as exc:
        QMessageBox.warning(parent, "Конвертация", str(exc))
        return False
    if result.resumed:
        sessions.touch_session(result.session_id, last_accessed_at=tick())
        conn.commit()

    if not sessions.list_rows(result.session_id):
        return False

    conversion = EmployeeConversionService(
        conn, session, employees, sessions=sessions, db_path=db_path
    )
    bulk = ConversionBulkReviewDialog(
        conversion=conversion,
        sessions=sessions,
        session_id=result.session_id,
        employees=employees,
        directories=directories,
        clock=tick,
        parent=parent,
    )
    connect_bulk_review_checkbox_updates(bulk)
    if bulk.exec() != QDialog.DialogCode.Accepted:
        return False

    if not sessions.list_rows(result.session_id):
        return True

    wizard = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=result.session_id,
        clock=tick,
        status_history=status_history,
        parent=parent,
    )
    return wizard.exec() == QDialog.DialogCode.Accepted


__all__ = ["run_conversion_wizard_flow"]
