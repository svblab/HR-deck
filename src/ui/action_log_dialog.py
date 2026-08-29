"""Диалог журнала действий: фильтры, таблица только для чтения, Excel (ТЗ §4.6)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.action_log import EXPORT_HEADERS, ActionLogFilters
from services.user_action_log import UserActionLogService

_MUTATING_LABELS = ("удал", "измен", "редакт", "сохранить", "добавить")


class ActionLogDialog(QDialog):
    def __init__(self, log: UserActionLogService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = log
        self.setObjectName("actionLogDialog")
        self.setWindowTitle("Журнал действий")
        self.setModal(True)
        self.setMinimumWidth(860)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._account = QComboBox(objectName="logFilterAccount")
        self._action = QComboBox(objectName="logFilterAction")
        self._employee = QComboBox(objectName="logFilterEmployee")
        self._template = QComboBox(objectName="logFilterTemplate")
        self._template.setToolTip("Фильтр по шаблону станет активным после EPIC-011")
        form.addRow("Пользователь", self._account)
        form.addRow("Тип действия", self._action)
        form.addRow("Сотрудник", self._employee)
        form.addRow("Шаблон", self._template)
        layout.addLayout(form)
        dates = QHBoxLayout()
        self._use_dates = QCheckBox("Период", objectName="logFilterUseDates")
        self._from = QDateEdit(objectName="logFilterDateFrom")
        self._to = QDateEdit(objectName="logFilterDateTo")
        today = QDate.currentDate()
        for widget in (self._from, self._to):
            widget.setCalendarPopup(True)
            widget.setDate(today)
            widget.setDisplayFormat("yyyy-MM-dd")
            widget.setEnabled(False)
        self._use_dates.toggled.connect(self._toggle_dates)
        dates.addWidget(self._use_dates)
        dates.addWidget(self._from)
        dates.addWidget(QLabel("по"))
        dates.addWidget(self._to)
        dates.addStretch(1)
        layout.addLayout(dates)
        buttons = QHBoxLayout()
        show_btn = QPushButton("Показать", objectName="logShowBtn")
        export_btn = QPushButton("Excel", objectName="logExportXlsx")
        show_btn.clicked.connect(self._reload)
        export_btn.clicked.connect(self._export)
        buttons.addWidget(show_btn)
        buttons.addWidget(export_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._grid = QTableWidget(objectName="actionLogTable")
        self._grid.setColumnCount(len(EXPORT_HEADERS))
        self._grid.setHorizontalHeaderLabels(list(EXPORT_HEADERS))
        self._grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._grid.verticalHeader().setVisible(False)
        header = self._grid.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._grid, stretch=1)
        self._status = QLabel(objectName="actionLogStatus")
        layout.addWidget(self._status)
        self._fill_filters()
        self._reload()

    def filters(self) -> ActionLogFilters:
        created_from = created_to = None
        if self._use_dates.isChecked():
            created_from = self._from.date().toString("yyyy-MM-dd")
            created_to = self._to.date().toString("yyyy-MM-dd")
        return ActionLogFilters(
            account_id=_combo_id(self._account),
            created_from=created_from,
            created_to=created_to,
            action_type=_combo_text(self._action),
            employee_id=_combo_id(self._employee),
            template_id=_combo_id(self._template),
        )

    def has_mutating_controls(self) -> bool:
        labels = [w.text().casefold() for w in self.findChildren(QPushButton)]
        labels.extend(w.text().casefold() for w in self.findChildren(QCheckBox))
        return any(any(token in text for token in _MUTATING_LABELS) for text in labels)

    def _fill_filters(self) -> None:
        _fill(self._account, self._log.list_accounts())
        self._action.clear()
        self._action.addItem("Все", None)
        for name in self._log.list_action_types():
            self._action.addItem(name, name)
        _fill(self._employee, self._log.list_employees())
        _fill(self._template, self._log.list_templates())

    def _toggle_dates(self, enabled: bool) -> None:
        self._from.setEnabled(enabled)
        self._to.setEnabled(enabled)

    def _reload(self) -> None:
        entries = self._log.list_entries(self.filters())
        self._grid.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            for j, value in enumerate(entry.export_cells()):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._grid.setItem(i, j, item)
        self._status.setText(f"Записей: {len(entries)}")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить журнал", "action-log.xlsx", "*.xlsx"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path = f"{path}.xlsx"
        count = self._log.export_xlsx(Path(path), self.filters())
        self._status.setText(f"Экспортировано: {count}")


def _combo_id(combo: QComboBox) -> int | None:
    data = combo.currentData()
    return int(data) if data is not None else None


def _combo_text(combo: QComboBox) -> str | None:
    data = combo.currentData()
    return str(data) if data is not None else None


def _fill(combo: QComboBox, items: list[tuple[int, str]]) -> None:
    combo.clear()
    combo.addItem("Все", None)
    for item_id, name in items:
        combo.addItem(name, item_id)
