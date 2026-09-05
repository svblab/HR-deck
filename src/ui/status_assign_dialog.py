"""Диалог назначения статуса сотрудника (EPIC-006 UI gap)."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from domain.permissions import Permission, has_permission
from domain.roster import format_display_date
from domain.status_assignment import StatusAssignmentPlan
from domain.status_periods import StatusPeriodError
from services.authorization import AuthorizationError
from services.availability_statuses import AvailabilityStatusService
from services.session import SessionState
from services.status_history import (
    ConfirmationRequiredError,
    StatusHistoryError,
    StatusHistoryService,
)
from ui.theme import TEXT_MUTED


def _plan_summary(plan: StatusAssignmentPlan) -> str:
    lines = ["Назначение затронет существующие периоды:", ""]
    for corr in plan.corrections:
        old = format_display_date(corr.old_value) if corr.old_value else "—"
        new = format_display_date(corr.new_value) if corr.new_value else "—"
        lines.append(f"• {corr.field_name}: {old} → {new} ({corr.reason})")
    for insert in plan.inserts:
        end = format_display_date(insert.end_date) if insert.end_date else "…"
        lines.append(
            f"• новый период: {format_display_date(insert.start_date)} — {end}"
        )
    lines.extend(["", "Продолжить?"])
    return "\n".join(lines)


class StatusAssignDialog(QDialog):
    def __init__(
        self,
        history: StatusHistoryService,
        statuses: AvailabilityStatusService,
        session: SessionState,
        *,
        employee_id: int,
        employee_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._history = history
        self._statuses = statuses
        self._session = session
        self._employee_id = employee_id
        self._can_manage = has_permission(session.role, Permission.MANAGE_STATUSES)

        self.setObjectName("statusAssignDialog")
        self.setWindowTitle(f"Статус — {employee_name}")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Назначение нового периода. При пересечении с существующими "
            "будет запрошено подтверждение."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(hint)

        form = QFormLayout()
        self._status = QComboBox(objectName="statusAssignStatus")
        self._start = QDateEdit(objectName="statusAssignStart")
        self._start.setCalendarPopup(True)
        self._start.setDisplayFormat("dd.MM.yyyy")
        self._start.setDate(QDate.currentDate())
        self._end = QDateEdit(objectName="statusAssignEnd")
        self._end.setCalendarPopup(True)
        self._end.setDisplayFormat("dd.MM.yyyy")
        self._end.setDate(QDate.currentDate())
        self._end_empty = QComboBox(objectName="statusAssignEndMode")
        self._end_empty.addItem("Без даты окончания", False)
        self._end_empty.addItem("Указать дату окончания", True)
        self._note = QLineEdit(objectName="statusAssignNote")
        form.addRow("Статус", self._status)
        form.addRow("Начало", self._start)
        form.addRow("Окончание", self._end_empty)
        form.addRow("", self._end)
        form.addRow("Примечание", self._note)
        layout.addLayout(form)

        hist_title = QLabel("История (эффективная)")
        hist_title.setStyleSheet("font-weight: 600; margin-top: 8px;")
        layout.addWidget(hist_title)
        self._history_label = QLabel(objectName="statusAssignHistory")
        self._history_label.setWordWrap(True)
        self._history_label.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self._history_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._save = buttons.addButton(
            "Назначить", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._save.setObjectName("statusAssignSaveBtn")
        self._save.setEnabled(self._can_manage)
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._status.currentIndexChanged.connect(self._on_status_changed)
        self._end_empty.currentIndexChanged.connect(self._sync_end_enabled)
        self._fill_statuses()
        self._refresh_history()
        self._on_status_changed()
        if not self._can_manage:
            for widget in (self._status, self._start, self._end, self._end_empty, self._note):
                widget.setEnabled(False)

    def _fill_statuses(self) -> None:
        self._status.blockSignals(True)
        self._status.clear()
        for row in self._statuses.list_statuses(active_only=True):
            self._status.addItem(row.name, row.id)
        self._status.blockSignals(False)

    def _selected_status(self):
        status_id = self._status.currentData()
        if status_id is None:
            return None
        for row in self._statuses.list_statuses(active_only=True):
            if row.id == status_id:
                return row
        return None

    def _on_status_changed(self) -> None:
        status = self._selected_status()
        policy = status.end_date_policy if status is not None else 0
        if policy == 1:
            self._end_empty.setCurrentIndex(1)
            self._end_empty.setEnabled(False)
        elif policy == 0:
            self._end_empty.setCurrentIndex(0)
            self._end_empty.setEnabled(False)
        else:
            self._end_empty.setEnabled(self._can_manage)
        self._sync_end_enabled()

    def _sync_end_enabled(self) -> None:
        use_end = bool(self._end_empty.currentData())
        self._end.setEnabled(self._can_manage and use_end)

    def _refresh_history(self) -> None:
        try:
            rows = self._history.effective_timeline(self._employee_id)
        except (AuthorizationError, StatusHistoryError) as exc:
            self._history_label.setText(str(exc))
            return
        if not rows:
            self._history_label.setText("Нет записей")
            return
        names = {s.id: s.name for s in self._statuses.list_statuses(active_only=False)}
        lines = []
        for entry in sorted(rows, key=lambda r: (r.start_date, r.id), reverse=True)[:8]:
            end = format_display_date(entry.end_date) if entry.end_date else "…"
            name = names.get(entry.status_id, f"#{entry.status_id}")
            lines.append(
                f"{format_display_date(entry.start_date)} — {end} · {name}"
            )
        self._history_label.setText("\n".join(lines))

    def _submit(self) -> None:
        status_id = self._status.currentData()
        if status_id is None:
            QMessageBox.warning(self, "Статус", "Выберите статус.")
            return
        start = self._start.date().toString("yyyy-MM-dd")
        end: str | None = None
        if bool(self._end_empty.currentData()):
            end = self._end.date().toString("yyyy-MM-dd")
        note = self._note.text().strip() or None
        try:
            self._history.assign_status(
                self._employee_id,
                status_id=int(status_id),
                start_date=start,
                end_date=end,
                note=note,
            )
        except ConfirmationRequiredError as exc:
            answer = QMessageBox.warning(
                self,
                "Подтверждение изменений",
                _plan_summary(exc.plan),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                self._history.assign_status(
                    self._employee_id,
                    status_id=int(status_id),
                    start_date=start,
                    end_date=end,
                    note=note,
                    confirmed=True,
                )
            except (
                AuthorizationError,
                StatusHistoryError,
                StatusPeriodError,
            ) as err:
                QMessageBox.warning(self, "Статус", str(err))
                return
        except (AuthorizationError, StatusHistoryError, StatusPeriodError) as exc:
            QMessageBox.warning(self, "Статус", str(exc))
            return
        self.accept()
