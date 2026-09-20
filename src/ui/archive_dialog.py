"""Диалог архива уволенных сотрудников: поиск, восстановление, назначение статуса."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.permissions import Permission, has_permission
from domain.roster import RosterFilters, RosterRow
from services.availability_statuses import AvailabilityStatusService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.roster import RosterService
from services.session import SessionState
from services.status_history import StatusHistoryService
from ui.employee_card_form import EmployeeCardDialog
from ui.status_assign_dialog import StatusAssignDialog


class ArchiveDialog(QDialog):
    def __init__(
        self,
        roster: RosterService,
        employees: EmployeeService,
        directories: DirectoryService,
        history: StatusHistoryService,
        statuses: AvailabilityStatusService,
        session: SessionState,
        *,
        on_changed: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("archiveDialog")
        self.setWindowTitle("Архив")
        self.setModal(True)
        self.setMinimumSize(720, 420)
        self._roster = roster
        self._employees = employees
        self._directories = directories
        self._history = history
        self._statuses = statuses
        self._session = session
        self._on_changed = on_changed
        self._rows: list[RosterRow] = []
        self._selected: RosterRow | None = None

        layout = QVBoxLayout(self)
        search_row = QHBoxLayout()
        self._search = QLineEdit(objectName="archiveSearchInput")
        self._search.setPlaceholderText("Поиск по ФИО…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._reload)
        search_row.addWidget(QLabel("Поиск"))
        search_row.addWidget(self._search, stretch=1)
        layout.addLayout(search_row)

        self._table = QTableWidget(objectName="archiveTable")
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["ФИО", "Филиал", "Должность", "Текущий статус"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, stretch=1)

        actions = QHBoxLayout()
        self._open_card_btn = QPushButton("Открыть карточку", objectName="archiveOpenCardBtn")
        self._open_card_btn.clicked.connect(self._open_selected_card)
        self._restore_btn = QPushButton("Восстановить", objectName="archiveRestoreBtn")
        self._restore_btn.clicked.connect(self._restore_selected)
        self._restore_assign_btn = QPushButton(
            "Восстановить и назначить статус…",
            objectName="archiveRestoreAssignBtn",
        )
        self._restore_assign_btn.clicked.connect(self._restore_and_assign_status)
        actions.addWidget(self._open_card_btn)
        actions.addWidget(self._restore_btn)
        actions.addWidget(self._restore_assign_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        close_box.accepted.connect(self.accept)
        layout.addWidget(close_box)

        self._can_view = has_permission(session.role, Permission.VIEW_EMPLOYEES)
        self._can_manage = has_permission(session.role, Permission.MANAGE_EMPLOYEES)
        self._reload()

    def _reload(self) -> None:
        query = self._search.text().strip()
        rows = self._roster.list_rows(
            include_archived=True,
            filters=RosterFilters(name_query=query),
        )
        self._rows = [row for row in rows if row.is_archived]
        self._table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            self._table.setItem(i, 0, QTableWidgetItem(row.full_name))
            self._table.setItem(i, 1, QTableWidgetItem(row.branch_name))
            self._table.setItem(i, 2, QTableWidgetItem(row.position_name))
            status = row.status_name or "—"
            self._table.setItem(i, 3, QTableWidgetItem(status))
        self._selected = None
        self._update_action_buttons()

    def _on_selection_changed(self) -> None:
        selected = self._table.selectionModel()
        if selected is None:
            self._selected = None
        else:
            indexes = selected.selectedRows()
            if not indexes:
                self._selected = None
            else:
                self._selected = self._rows[indexes[0].row()]
        self._update_action_buttons()

    def _update_action_buttons(self) -> None:
        has_selection = self._selected is not None
        self._open_card_btn.setEnabled(has_selection and self._can_view)
        self._restore_btn.setEnabled(has_selection and self._can_manage)
        self._restore_assign_btn.setEnabled(has_selection and self._can_manage)

    def _open_selected_card(self) -> None:
        if self._selected is None:
            return
        dialog = EmployeeCardDialog(
            self._employees,
            self._directories,
            self._session,
            employee_id=self._selected.employee_id,
            parent=self,
            status_history=self._history,
            availability_statuses=self._statuses,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._notify_changed()
        self._reload()

    def _restore_selected(self) -> None:
        if self._selected is None:
            return
        try:
            self._employees.restore_employee(self._selected.employee_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Архив", str(exc))
            return
        self._notify_changed()
        self._reload()

    def _restore_and_assign_status(self) -> None:
        if self._selected is None:
            return
        row = self._selected
        try:
            self._employees.restore_employee(row.employee_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Архив", str(exc))
            return
        self._notify_changed()
        dialog = StatusAssignDialog(
            self._history,
            self._statuses,
            self._session,
            employee_id=row.employee_id,
            employee_name=row.full_name,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._notify_changed()
        self._reload()

    def _notify_changed(self) -> None:
        if self._on_changed is not None:
            self._on_changed()
