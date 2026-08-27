"""Панель доска/таблица, фильтры, поиск, группировка (EPIC-008)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from domain.permissions import Permission, has_permission
from domain.roster import (
    GroupBy,
    RosterFilters,
    RosterRow,
    apply_filters,
    group_rows,
    summary_counts,
)
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.roster import RosterService
from services.session import SessionState
from services.standard_reports import StandardReportService
from ui.board_widget import BoardWidget
from ui.employee_card_form import EmployeeCardDialog
from ui.employee_popup import EmployeePopupDialog
from ui.import_export_dialog import run_export_flow, run_import_flow
from ui.reports_dialog import ReportsDialog
from ui.table_widget import TableWidget


class RosterPanel(QWidget):
    filters_reset = Signal()

    def __init__(
        self,
        service: RosterService,
        parent: QWidget | None = None,
        *,
        employees: EmployeeService | None = None,
        directories: DirectoryService | None = None,
        session: SessionState | None = None,
        reports: StandardReportService | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._employees = employees
        self._directories = directories
        self._session = session
        self._reports = reports
        self._all_rows: list[RosterRow] = []
        self._group_by = GroupBy.STATUS
        self._name_query = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())
        self._stack = QStackedWidget()
        self._board = BoardWidget()
        self._table = TableWidget()
        self._board.employee_activated.connect(self._open_popup)
        self._table.employee_activated.connect(self._open_popup)
        self._stack.addWidget(self._board)
        self._stack.addWidget(self._table)
        layout.addWidget(self._stack, stretch=1)
        self.reload()

    def set_name_query(self, text: str) -> None:
        self._name_query = text
        self._render()

    def reload(self) -> None:
        self._all_rows = self._service.list_rows()
        self._fill_branch_combo()
        self._render()

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget(objectName="toolbar")
        outer = QVBoxLayout(toolbar)
        outer.setContentsMargins(20, 10, 20, 10)
        outer.setSpacing(10)

        row1 = QHBoxLayout()
        self._add_btn = QPushButton("+ Добавить сотрудника", objectName="addEmployeeBtn")
        can_add = self._session is not None and has_permission(
            self._session.role, Permission.MANAGE_EMPLOYEES
        )
        self._add_btn.setEnabled(bool(can_add and self._employees and self._directories))
        self._add_btn.clicked.connect(self._open_create_form)
        can_io = self._session is not None and has_permission(
            self._session.role, Permission.IMPORT_EXPORT
        )
        self._import_btn = QPushButton("Импорт", objectName="importEmployeesBtn")
        self._export_btn = QPushButton("Экспорт", objectName="exportEmployeesBtn")
        io_enabled = bool(can_io and self._employees and self._directories)
        self._import_btn.setEnabled(io_enabled)
        self._export_btn.setEnabled(io_enabled)
        self._import_btn.clicked.connect(self._open_import)
        self._export_btn.clicked.connect(self._open_export)
        self._reports_btn = QPushButton("Отчёты", objectName="reportsBtn")
        can_reports = self._session is not None and has_permission(
            self._session.role, Permission.VIEW_STANDARD_REPORTS
        )
        self._reports_btn.setEnabled(bool(can_reports and self._reports and self._directories))
        self._reports_btn.clicked.connect(self._open_reports)
        self._board_btn = QPushButton("Доска", objectName="viewToggleActive")
        self._table_btn = QPushButton("Таблица", objectName="viewToggleInactive")
        self._board_btn.clicked.connect(lambda: self._set_view(0))
        self._table_btn.clicked.connect(lambda: self._set_view(1))
        row1.addWidget(self._add_btn)
        row1.addWidget(self._import_btn)
        row1.addWidget(self._export_btn)
        row1.addWidget(self._reports_btn)
        row1.addWidget(self._board_btn)
        row1.addWidget(self._table_btn)
        row1.addStretch(1)
        self._summary = QLabel()
        self._summary.setObjectName("summaryStrip")
        row1.addWidget(self._summary)
        self._clarify_btn = QPushButton("Требуют уточнения: 0")
        self._clarify_btn.setObjectName("clarificationCounter")
        self._clarify_btn.clicked.connect(self._toggle_only_clarification)
        row1.addWidget(self._clarify_btn)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        self._branch = QComboBox()
        self._branch.setObjectName("filterBranch")
        self._dept = QComboBox()
        self._dept.setObjectName("filterDept")
        self._div = QComboBox()
        self._div.setObjectName("filterDivision")
        self._branch.currentIndexChanged.connect(self._on_branch_changed)
        self._dept.currentIndexChanged.connect(self._on_dept_changed)
        self._div.currentIndexChanged.connect(self._on_div_changed)
        reset = QPushButton("Показать всех", objectName="filterReset")
        reset.clicked.connect(self.reset_filters)
        self._group_combo = QComboBox()
        self._group_combo.setObjectName("groupByCombo")
        self._group_combo.addItem("По статусу", GroupBy.STATUS)
        self._group_combo.addItem("По филиалу", GroupBy.BRANCH)
        self._group_combo.addItem("По департаменту", GroupBy.DEPARTMENT)
        self._group_combo.currentIndexChanged.connect(self._on_group_changed)
        self._only_clarify = QCheckBox("Только требующие уточнения")
        self._only_clarify.setObjectName("clarifyFilter")
        self._only_clarify.toggled.connect(self._render)
        row2.addWidget(self._branch)
        row2.addWidget(self._dept)
        row2.addWidget(self._div)
        row2.addWidget(reset)
        row2.addWidget(self._group_combo)
        row2.addWidget(self._only_clarify)
        row2.addStretch(1)
        outer.addLayout(row2)
        return toolbar

    def reset_filters(self) -> None:
        self._name_query = ""
        self._only_clarify.setChecked(False)
        self._group_combo.setCurrentIndex(0)
        self._fill_branch_combo()
        self.filters_reset.emit()
        self._render()

    def _set_view(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        board_active = index == 0
        self._board_btn.setObjectName("viewToggleActive" if board_active else "viewToggleInactive")
        table_name = "viewToggleActive" if not board_active else "viewToggleInactive"
        self._table_btn.setObjectName(table_name)
        self._board_btn.style().unpolish(self._board_btn)
        self._board_btn.style().polish(self._board_btn)
        self._table_btn.style().unpolish(self._table_btn)
        self._table_btn.style().polish(self._table_btn)
        self._render()

    def _toggle_only_clarification(self) -> None:
        self._only_clarify.setChecked(not self._only_clarify.isChecked())

    def _on_group_changed(self) -> None:
        data = self._group_combo.currentData()
        if data is not None:
            self._group_by = GroupBy(data)
        self._render()

    def _combo_id(self, combo: QComboBox) -> int | None:
        data = combo.currentData()
        return int(data) if data is not None else None

    def _fill_branch_combo(self) -> None:
        self._branch.blockSignals(True)
        self._branch.clear()
        self._branch.addItem("Все филиалы", None)
        for branch in self._service.filter_branches():
            self._branch.addItem(branch.name, branch.id)
        self._branch.blockSignals(False)
        self._fill_dept_combo()

    def _fill_dept_combo(self) -> None:
        self._dept.blockSignals(True)
        self._dept.clear()
        self._dept.addItem("Все департаменты", None)
        for dept in self._service.filter_departments(branch_id=self._combo_id(self._branch)):
            self._dept.addItem(dept.name, dept.id)
        self._dept.blockSignals(False)
        self._fill_div_combo()

    def _fill_div_combo(self) -> None:
        self._div.blockSignals(True)
        self._div.clear()
        self._div.addItem("Все отделы", None)
        dept_id = self._combo_id(self._dept)
        if dept_id is not None:
            for div in self._service.filter_divisions(department_id=dept_id):
                self._div.addItem(div.name, div.id)
        self._div.blockSignals(False)

    def _on_branch_changed(self) -> None:
        self._fill_dept_combo()
        self._render()

    def _on_dept_changed(self) -> None:
        self._fill_div_combo()
        self._render()

    def _on_div_changed(self) -> None:
        self._render()

    def _filters(self) -> RosterFilters:
        return RosterFilters(
            name_query=self._name_query,
            branch_id=self._combo_id(self._branch),
            department_id=self._combo_id(self._dept),
            division_id=self._combo_id(self._div),
            only_needing_clarification=self._only_clarify.isChecked(),
        )

    def _render(self) -> None:
        filtered = apply_filters(self._all_rows, self._filters())
        total, by_status, needing = summary_counts(filtered)
        parts = [f"<b>{total}</b> сотрудников"]
        parts.extend(f"{name}: <b>{n}</b>" for name, n in by_status.items() if n)
        self._summary.setText(" · ".join(parts))
        self._summary.setTextFormat(Qt.TextFormat.RichText)
        self._clarify_btn.setText(f"Требуют уточнения: {needing}")
        columns = group_rows(filtered, self._group_by, self._service.column_specs(self._group_by))
        self._board.set_columns(columns)
        self._table.set_rows(filtered)

    def _open_popup(self, employee_id: int) -> None:
        row = next((r for r in self._all_rows if r.employee_id == employee_id), None)
        if row is None:
            return
        history = self._service.history_preview(employee_id)
        popup = EmployeePopupDialog(row, history, self)
        popup.exec()
        if popup.open_card_id is not None:
            self._open_card(popup.open_card_id)

    def _open_create_form(self) -> None:
        self._open_card(None)

    def _open_card(self, employee_id: int | None) -> None:
        if self._employees is None or self._directories is None or self._session is None:
            return
        dialog = EmployeeCardDialog(
            self._employees,
            self._directories,
            self._session,
            employee_id=employee_id,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.reload()

    def _open_import(self) -> None:
        if self._employees is None or self._directories is None or self._session is None:
            return
        if run_import_flow(self, self._employees, self._directories, self._session):
            self.reload()

    def _open_export(self) -> None:
        if self._employees is None or self._directories is None or self._session is None:
            return
        run_export_flow(self, self._employees, self._directories, self._session)

    def _open_reports(self) -> None:
        if self._reports is None or self._directories is None or self._employees is None:
            return
        ReportsDialog(self._reports, self._directories, self._employees, self).exec()
