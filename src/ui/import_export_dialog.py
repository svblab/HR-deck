"""Диалог предпросмотра импорта сотрудников (ТЗ §3.7)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.employee_import import ImportPreview
from services.directories import DirectoryService
from services.employee_export import EmployeeExportService
from services.employee_import import EmployeeImportError, EmployeeImportService
from services.employees import EmployeeService
from services.session import SessionState


class ImportPreviewDialog(QDialog):
    def __init__(self, preview: ImportPreview, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("importPreviewDialog")
        self.setWindowTitle("Предпросмотр импорта")
        self.setModal(True)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        summary = QLabel(
            f"К созданию: {len(preview.ready)} · "
            f"ошибок: {len(preview.errors)} · "
            f"предупреждений: {len(preview.warnings)}"
        )
        summary.setObjectName("importPreviewSummary")
        layout.addWidget(summary)
        if preview.errors:
            layout.addWidget(QLabel("Ошибки (эти строки не будут созданы)"))
            layout.addWidget(_issue_table(preview.errors, "importErrorTable"))
        if preview.warnings:
            layout.addWidget(QLabel("Возможные дубли (не блокируют создание)"))
            layout.addWidget(_issue_table(preview.warnings, "importWarningTable"))
        if preview.ready:
            layout.addWidget(QLabel("Будут созданы"))
            ready = QTableWidget(len(preview.ready), 2, objectName="importReadyTable")
            ready.setHorizontalHeaderLabels(["Строка", "ФИО"])
            for idx, row in enumerate(preview.ready):
                ready.setItem(idx, 0, QTableWidgetItem(str(row.source_row)))
                ready.setItem(idx, 1, QTableWidgetItem(row.payload.full_name))
            ready.resizeColumnsToContents()
            layout.addWidget(ready)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        if preview.ready:
            confirm = buttons.addButton(
                "Подтвердить импорт", QDialogButtonBox.ButtonRole.AcceptRole
            )
            confirm.setObjectName("confirmImportBtn")
            buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def run_import_flow(
    parent: QWidget,
    employees: EmployeeService,
    directories: DirectoryService,
    session: SessionState,
) -> bool:
    path, _filter = QFileDialog.getOpenFileName(
        parent,
        "Импорт сотрудников",
        "",
        "Таблицы (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv)",
    )
    if not path:
        return False
    service = EmployeeImportService(employees, directories, session)
    try:
        preview = service.preview_path(Path(path))
    except EmployeeImportError as exc:
        QMessageBox.warning(parent, "Импорт", str(exc))
        return False
    dialog = ImportPreviewDialog(preview, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    service.confirm(preview)
    return True


def run_export_flow(
    parent: QWidget,
    employees: EmployeeService,
    directories: DirectoryService,
    session: SessionState,
) -> None:
    path, _filter = QFileDialog.getSaveFileName(
        parent,
        "Экспорт сотрудников",
        "employees.xlsx",
        "Excel (*.xlsx)",
    )
    if not path:
        return
    if not path.lower().endswith(".xlsx"):
        path = f"{path}.xlsx"
    EmployeeExportService(employees, directories, session).export_xlsx(Path(path))


def _issue_table(issues: tuple, object_name: str) -> QTableWidget:
    table = QTableWidget(len(issues), 2, objectName=object_name)
    table.setHorizontalHeaderLabels(["Строка", "Сообщение"])
    for idx, issue in enumerate(issues):
        table.setItem(idx, 0, QTableWidgetItem(str(issue.source_row)))
        table.setItem(idx, 1, QTableWidgetItem(issue.message))
    table.resizeColumnsToContents()
    return table
