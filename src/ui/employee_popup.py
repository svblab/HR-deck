"""Всплывающая карточка сотрудника с текущим статусом и краткой историей (ТЗ §3.6)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from domain.roster import HistoryPreviewRow, RosterRow, format_display_date
from ui.board_widget import status_chip_style, subdivision_label
from ui.theme import BORDER, TEXT_MUTED


class EmployeePopupDialog(QDialog):
    def __init__(
        self,
        row: RosterRow,
        history: list[HistoryPreviewRow],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(row.full_name)
        self.setModal(True)
        self._row = row
        self.open_card_id: int | None = None
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        name = QLabel(row.full_name)
        name.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(name)
        role = QLabel(row.position_name)
        role.setStyleSheet(f"font-size: 13px; color: {TEXT_MUTED};")
        layout.addWidget(role)
        layout.addWidget(_kv("Филиал", row.branch_name))
        layout.addWidget(_kv("Подразделение", subdivision_label(row) or "—"))
        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 8, 0, 8)
        status_layout.addWidget(QLabel("Текущий статус"))
        status_layout.addStretch(1)
        tag = QLabel(row.status_name or "Требует уточнения")
        tag.setStyleSheet(status_chip_style(row.status_color_hex if row.status_name else "#A32D2D"))
        tag.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_layout.addWidget(tag)
        layout.addWidget(status_row)
        layout.addWidget(_kv("Дата начала", format_display_date(row.start_date)))
        end_label = format_display_date(row.end_date)
        if row.needs_clarification and row.end_date:
            end_label = f"Просрочено · {end_label}"
        layout.addWidget(_kv("Дата окончания", end_label))

        hist_title = QLabel("Краткая история")
        hist_title.setStyleSheet("font-weight: 600; margin-top: 8px;")
        layout.addWidget(hist_title)
        if not history:
            empty = QLabel("Нет записей")
            empty.setStyleSheet(f"color: {TEXT_MUTED};")
            layout.addWidget(empty)
        for entry in history:
            layout.addWidget(
                QLabel(
                    f"{format_display_date(entry.start_date)} — "
                    f"{format_display_date(entry.end_date) if entry.end_date else '…'}"
                    f"  · {entry.status_name}"
                )
            )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        card_btn = buttons.addButton("Карточка", QDialogButtonBox.ButtonRole.ActionRole)
        card_btn.setObjectName("openEmployeeCard")
        card_btn.clicked.connect(self._open_card)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _open_card(self) -> None:
        self.open_card_id = self._row.employee_id
        self.accept()


def _kv(label: str, value: str) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 8, 0, 8)
    left = QLabel(label)
    left.setStyleSheet(f"color: {TEXT_MUTED};")
    layout.addWidget(left)
    layout.addStretch(1)
    layout.addWidget(QLabel(value))
    row.setStyleSheet(f"border-bottom: 1px solid {BORDER};")
    return row
