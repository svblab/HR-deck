"""Диалог стандартных отчётов: параметры, предпросмотр, Excel/PDF (ТЗ §3.8.1)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.reports import (
    REPORT_SPECS,
    ReportGroupBy,
    ReportKind,
    ReportParam,
    ReportParams,
    ReportTable,
    uses_param,
)
from reports.pdf_export import write_report_pdf
from reports.xlsx_export import write_report_xlsx
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.standard_reports import StandardReportService


class ReportsDialog(QDialog):
    def __init__(
        self,
        reports: StandardReportService,
        directories: DirectoryService,
        employees: EmployeeService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._reports = reports
        self._directories = directories
        self._employees = employees
        self._table: ReportTable | None = None
        self.setObjectName("reportsDialog")
        self.setWindowTitle("Отчёты")
        self.setModal(True)
        self.setMinimumWidth(720)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._kind = QComboBox(objectName="reportKind")
        for kind, spec in REPORT_SPECS.items():
            self._kind.addItem(spec.title, kind)
        self._kind.currentIndexChanged.connect(self._sync_params)
        form.addRow("Отчёт", self._kind)
        self._from = QDateEdit(objectName="reportDateFrom")
        self._to = QDateEdit(objectName="reportDateTo")
        today = QDate.currentDate()
        for widget in (self._from, self._to):
            widget.setCalendarPopup(True)
            widget.setDate(today)
            widget.setDisplayFormat("yyyy-MM-dd")
        form.addRow("Период с", self._from)
        form.addRow("по", self._to)
        self._branch = QComboBox(objectName="reportBranch")
        self._dept = QComboBox(objectName="reportDept")
        self._div = QComboBox(objectName="reportDiv")
        self._status = QComboBox(objectName="reportStatus")
        self._employment = QComboBox(objectName="reportEmployment")
        self._employee = QComboBox(objectName="reportEmployee")
        self._group = QComboBox(objectName="reportGroupBy")
        self._group.addItem("По филиалу", ReportGroupBy.BRANCH)
        self._group.addItem("По департаменту", ReportGroupBy.DEPARTMENT)
        form.addRow("Филиал", self._branch)
        form.addRow("Департамент", self._dept)
        form.addRow("Отдел", self._div)
        form.addRow("Статус", self._status)
        form.addRow("Тип занятости", self._employment)
        form.addRow("Сотрудник", self._employee)
        form.addRow("Группировка", self._group)
        layout.addLayout(form)
        preview_btn = QPushButton("Сформировать", objectName="reportPreviewBtn")
        preview_btn.clicked.connect(self._preview)
        layout.addWidget(preview_btn)
        self._grid = QTableWidget(objectName="reportPreviewTable")
        layout.addWidget(self._grid, stretch=1)
        export_row = QHBoxLayout()
        xlsx_btn = QPushButton("Excel", objectName="reportExportXlsx")
        pdf_btn = QPushButton("PDF", objectName="reportExportPdf")
        xlsx_btn.clicked.connect(lambda: self._export("xlsx"))
        pdf_btn.clicked.connect(lambda: self._export("pdf"))
        export_row.addWidget(xlsx_btn)
        export_row.addWidget(pdf_btn)
        export_row.addStretch(1)
        layout.addLayout(export_row)
        self._status_label = QLabel()
        layout.addWidget(self._status_label)
        self._fill_filters()
        self._sync_params()

    def _fill_filters(self) -> None:
        branches = [(b.id, b.name) for b in self._directories.list_branches(active_only=True)]
        _fill(self._branch, branches)
        self._branch.currentIndexChanged.connect(self._fill_depts)
        self._dept.currentIndexChanged.connect(self._fill_divs)
        self._fill_depts()
        _fill(self._status, self._reports.status_options())
        _fill(
            self._employment,
            [(t.id, t.name) for t in self._directories.list_employment_types(active_only=True)],
        )
        _fill(
            self._employee,
            [(c.id, c.full_name) for c in self._employees.list_employees(active_only=True)],
        )

    def _fill_depts(self) -> None:
        branch_id = _combo_id(self._branch)
        items = self._directories.list_departments(branch_id=branch_id, active_only=True)
        _fill(self._dept, [(d.id, d.name) for d in items])
        self._fill_divs()

    def _fill_divs(self) -> None:
        dept_id = _combo_id(self._dept)
        items = (
            self._directories.list_divisions(department_id=dept_id, active_only=True)
            if dept_id is not None
            else []
        )
        _fill(self._div, [(d.id, d.name) for d in items])

    def _sync_params(self) -> None:
        kind = self._kind.currentData()
        self._from.setEnabled(uses_param(kind, ReportParam.PERIOD))
        self._to.setEnabled(uses_param(kind, ReportParam.PERIOD) or kind == ReportKind.SNAPSHOT)
        self._branch.setEnabled(uses_param(kind, ReportParam.BRANCH))
        self._dept.setEnabled(uses_param(kind, ReportParam.DEPARTMENT))
        self._div.setEnabled(uses_param(kind, ReportParam.DIVISION))
        self._status.setEnabled(uses_param(kind, ReportParam.STATUS))
        self._employment.setEnabled(uses_param(kind, ReportParam.EMPLOYMENT_TYPE))
        self._employee.setEnabled(uses_param(kind, ReportParam.EMPLOYEE))
        self._group.setEnabled(uses_param(kind, ReportParam.GROUP_BY))

    def _params(self) -> ReportParams:
        kind = self._kind.currentData()
        group = self._group.currentData() or ReportGroupBy.BRANCH
        period = uses_param(kind, ReportParam.PERIOD)
        return ReportParams(
            date_from=self._from.date().toString("yyyy-MM-dd") if period else None,
            date_to=self._to.date().toString("yyyy-MM-dd")
            if period or kind == ReportKind.SNAPSHOT
            else None,
            branch_id=_combo_id(self._branch) if uses_param(kind, ReportParam.BRANCH) else None,
            department_id=_combo_id(self._dept)
            if uses_param(kind, ReportParam.DEPARTMENT)
            else None,
            division_id=_combo_id(self._div) if uses_param(kind, ReportParam.DIVISION) else None,
            status_id=_combo_id(self._status) if uses_param(kind, ReportParam.STATUS) else None,
            employment_type_id=_combo_id(self._employment)
            if uses_param(kind, ReportParam.EMPLOYMENT_TYPE)
            else None,
            employee_id=_combo_id(self._employee)
            if uses_param(kind, ReportParam.EMPLOYEE)
            else None,
            group_by=group,
        )

    def _preview(self) -> None:
        kind = self._kind.currentData()
        if uses_param(kind, ReportParam.EMPLOYEE) and _combo_id(self._employee) is None:
            QMessageBox.warning(self, "Отчёт", "Выберите сотрудника.")
            return
        self._table = self._reports.build(kind, self._params())
        grouped = any(r.group_label for r in self._table.rows)
        headers = list(self._table.columns) if not grouped else ["Группа", *self._table.columns]
        self._grid.setColumnCount(len(headers))
        self._grid.setHorizontalHeaderLabels(headers)
        self._grid.setRowCount(len(self._table.rows))
        for i, row in enumerate(self._table.rows):
            cells = list(row.cells) if not grouped else [row.group_label, *row.cells]
            for j, value in enumerate(cells):
                self._grid.setItem(i, j, QTableWidgetItem(value))
        self._status_label.setText(f"{self._table.title}: {len(self._table.rows)} строк")

    def _export(self, fmt: str) -> None:
        if self._table is None:
            self._preview()
        if self._table is None:
            return
        suffix = f"*.{fmt}"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчёт", f"report.{fmt}", suffix)
        if not path:
            return
        if not path.lower().endswith(f".{fmt}"):
            path = f"{path}.{fmt}"
        target = Path(path)
        if fmt == "xlsx":
            write_report_xlsx(target, self._table)
        else:
            write_report_pdf(target, self._table)


def _combo_id(combo: QComboBox) -> int | None:
    data = combo.currentData()
    return int(data) if data is not None else None


def _fill(combo: QComboBox, items: list[tuple[int, str]]) -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("Все", None)
    for item_id, name in items:
        combo.addItem(name, item_id)
    combo.blockSignals(False)
