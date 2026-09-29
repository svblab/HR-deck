"""EPIC-018 / Issue #124: bulk-review modal before conversion wizard (ADR-0012 addendum)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from data.import_sessions import ImportSessionRepository
from domain.employee import EmployeeCreateInput
from services.conversion_bulk_readiness import (
    ConversionBulkRowClassification,
    classify_conversion_rows,
)
from services.directories import DirectoryService
from services.employee_conversion import EmployeeConversionError, EmployeeConversionService
from services.employees import EmployeeService

Clock = Callable[[], str]

_STATUS_READY = "Готово к применению"
_STATUS_REVIEW = "Требует проверки"


class ConversionBulkReviewDialog(QDialog):
    """List staged conversion rows; apply unambiguous matches in bulk."""

    def __init__(
        self,
        *,
        conversion: EmployeeConversionService,
        sessions: ImportSessionRepository,
        session_id: int,
        employees: EmployeeService,
        directories: DirectoryService,
        clock: Clock,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conversion = conversion
        self._sessions = sessions
        self._session_id = session_id
        self._employees = employees
        self._directories = directories
        self._clock = clock
        self._rows: list[ConversionBulkRowClassification] = []

        self.setObjectName("conversionBulkReviewDialog")
        self.setWindowTitle("Массовое применение конвертации")
        self.setModal(True)
        self.setMinimumSize(720, 420)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Строки с однозначным сопоставлением справочников можно применить "
            "сразу. Остальные будут обработаны в построчном визарде."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._summary = QLabel(objectName="conversionBulkReviewSummary")
        root.addWidget(self._summary)

        self._table = QTableWidget(objectName="conversionBulkReviewTable")
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(
            ["", "Строка", "ФИО", "Статус"]
        )
        header = self._table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._table, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._continue_btn = buttons.addButton(
            "Продолжить в визард", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._continue_btn.setObjectName("conversionBulkReviewContinueBtn")
        self._apply_btn = QPushButton(
            "Применить отмеченные (0)", objectName="conversionBulkReviewApplyBtn"
        )
        apply_row = QHBoxLayout()
        apply_row.addWidget(self._apply_btn)
        apply_row.addStretch(1)
        apply_row.addWidget(buttons)
        root.addLayout(apply_row)

        buttons.rejected.connect(self.reject)
        self._continue_btn.clicked.connect(self.accept)
        self._apply_btn.clicked.connect(self._on_apply_selected)

        self._reload_table()

    def _reload_table(self) -> None:
        staged = self._sessions.list_rows(self._session_id)
        self._rows = classify_conversion_rows(
            staged, directories=self._directories, employees=self._employees
        )
        self._table.setRowCount(len(self._rows))
        ready_count = 0
        for idx, row in enumerate(self._rows):
            checkbox = QCheckBox(objectName="conversionBulkReviewRowCheck")
            checkbox.setProperty("row_id", row.row_id)
            if row.kind == "ready":
                checkbox.setEnabled(True)
                checkbox.setChecked(True)
                ready_count += 1
            else:
                checkbox.setEnabled(False)
                checkbox.setChecked(False)
            self._table.setCellWidget(idx, 0, checkbox)
            self._table.setItem(
                idx, 1, QTableWidgetItem(str(row.source_row_number))
            )
            self._table.setItem(idx, 2, QTableWidgetItem(row.full_name))
            status = _STATUS_READY if row.kind == "ready" else _STATUS_REVIEW
            self._table.setItem(idx, 3, QTableWidgetItem(status))
        self._summary.setText(
            f"Всего строк: {len(self._rows)} · готово к применению: {ready_count} · "
            f"требует проверки: {len(self._rows) - ready_count}"
        )
        self._update_apply_label()
        connect_bulk_review_checkbox_updates(self)

    def _update_apply_label(self) -> None:
        selected = len(self._selected_ready_rows())
        self._apply_btn.setText(f"Применить отмеченные ({selected})")
        self._apply_btn.setEnabled(selected > 0)

    def _selected_ready_rows(self) -> list[tuple[int, EmployeeCreateInput]]:
        by_id = {row.row_id: row for row in self._rows}
        selected: list[tuple[int, EmployeeCreateInput]] = []
        for idx in range(self._table.rowCount()):
            widget = self._table.cellWidget(idx, 0)
            if not isinstance(widget, QCheckBox):
                continue
            if not widget.isEnabled() or not widget.isChecked():
                continue
            row_id = int(widget.property("row_id"))
            view = by_id[row_id]
            if view.resolved is None:
                continue
            selected.append((row_id, view.resolved))
        return selected

    def _on_apply_selected(self) -> None:
        batch = self._selected_ready_rows()
        if not batch:
            return
        now = self._clock()
        try:
            result = self._conversion.save_rows_bulk(
                session_id=self._session_id,
                resolved_rows=batch,
                last_accessed_at=now,
            )
        except EmployeeConversionError as exc:
            QMessageBox.warning(self, "Массовое применение", str(exc))
            return

        source_by_id = {row.row_id: row.source_row_number for row in self._rows}
        lines = [
            f"Создано: {result.applied_count}",
            f"Ошибок: {result.error_count}",
        ]
        for item in result.results:
            if item.error_message:
                src = source_by_id.get(item.row_id, "?")
                lines.append(f"Строка {src} (id {item.row_id}): {item.error_message}")
        QMessageBox.information(
            self,
            "Результат массового применения",
            "\n".join(lines),
        )
        self._reload_table()

def connect_bulk_review_checkbox_updates(dialog: ConversionBulkReviewDialog) -> None:
    """Wire checkbox toggles to refresh Apply label (tests may call explicitly)."""
    table = dialog.findChild(QTableWidget, "conversionBulkReviewTable")
    if table is None:
        return
    for idx in range(table.rowCount()):
        widget = table.cellWidget(idx, 0)
        if isinstance(widget, QCheckBox):
            widget.toggled.connect(dialog._update_apply_label)


__all__ = ["ConversionBulkReviewDialog", "connect_bulk_review_checkbox_updates"]
