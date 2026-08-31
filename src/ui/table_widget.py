"""Табличный вид главного экрана (прототип)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from domain.roster import RosterRow, format_display_date
from ui.board_widget import subdivision_label


class TableWidget(QTableWidget):
    employee_activated = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 7, parent)
        self.setObjectName("rosterTable")
        self.setHorizontalHeaderLabels(
            ["ФИО", "Должность", "Филиал", "Подразделение", "Статус", "С даты", "По дату"]
        )
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.cellDoubleClicked.connect(self._on_cell)
        self.cellClicked.connect(self._on_cell)

    def set_rows(self, rows: list[RosterRow]) -> None:
        self.setRowCount(len(rows))
        for i, row in enumerate(rows):
            values = [
                row.full_name,
                row.position_name,
                row.branch_name,
                subdivision_label(row) or "—",
                row.status_name or "—",
                format_display_date(row.start_date) if row.start_date else "—",
                format_display_date(row.end_date) if row.end_date else "—",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, row.employee_id)
                if row.needs_clarification and col in {4, 6}:
                    item.setForeground(Qt.GlobalColor.red)
                self.setItem(i, col, item)

    def _on_cell(self, row: int, _column: int) -> None:
        item = self.item(row, 0)
        if item is None:
            return
        employee_id = item.data(Qt.ItemDataRole.UserRole)
        if employee_id is not None:
            self.employee_activated.emit(int(employee_id))
