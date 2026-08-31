"""Канбан-доска статусов (прототип prototype_glavny_ekran.html)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from domain.roster import RosterColumn, RosterRow, format_display_date
from ui.theme import TEXT, TEXT_MUTED


def status_chip_style(color_hex: str | None) -> str:
    fg = color_hex or "#5A5A55"
    return (
        f"background-color: {fg}22; color: {fg}; border-radius: 20px;"
        " padding: 2px 8px; font-size: 11px; font-weight: 500;"
    )


def subdivision_label(row: RosterRow) -> str:
    parts = [row.department_name]
    if row.division_name:
        parts.append(row.division_name)
    return " / ".join(p for p in parts if p)


def date_line(row: RosterRow) -> str:
    if not row.start_date and not row.end_date:
        return ""
    start = format_display_date(row.start_date)
    if row.end_date:
        text = f"{start} — {format_display_date(row.end_date)}"
    else:
        text = f"с {start}"
    if row.needs_clarification:
        return f"Просрочено · {text}"
    return text


class EmployeeCardWidget(QFrame):
    clicked = Signal(int)

    def __init__(self, row: RosterRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._employee_id = row.employee_id
        self.setObjectName("empCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 10, 11, 10)
        layout.setSpacing(2)
        name = QLabel(row.full_name)
        name.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TEXT};")
        layout.addWidget(name)
        role = QLabel(row.position_name)
        role.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED};")
        layout.addWidget(role)
        org = QLabel(f"{row.branch_name} · {subdivision_label(row)}")
        org.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED};")
        org.setWordWrap(True)
        layout.addWidget(org)
        if row.status_name:
            tag = QLabel(row.status_name)
            tag.setStyleSheet(status_chip_style(row.status_color_hex))
            layout.addWidget(tag)
        dates = date_line(row)
        if dates:
            date_lbl = QLabel(dates)
            date_lbl.setStyleSheet(
                "font-size: 11px; font-weight: 600; color: #A32D2D;"
                if row.needs_clarification
                else f"font-size: 11px; color: {TEXT_MUTED};"
            )
            layout.addWidget(date_lbl)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit(self._employee_id)
        super().mousePressEvent(event)


class BoardWidget(QScrollArea):
    employee_activated = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._inner = QWidget()
        self._layout = QHBoxLayout(self._inner)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(14)
        self._layout.addStretch(1)
        self.setWidget(self._inner)

    def set_columns(self, columns: list[RosterColumn]) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for column in columns:
            self._layout.insertWidget(self._layout.count() - 1, self._build_column(column))

    def _build_column(self, column: RosterColumn) -> QWidget:
        box = QFrame()
        box.setObjectName("boardColumn")
        box.setFixedWidth(242)
        box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(10, 10, 10, 10)
        head = QHBoxLayout()
        title = QLabel(column.title)
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        badge = QLabel(str(len(column.rows)))
        badge.setObjectName("countBadge")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(badge)
        outer.addLayout(head)
        cards = QVBoxLayout()
        cards.setSpacing(8)
        if not column.rows:
            empty = QLabel("Нет сотрудников")
            empty.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED};")
            cards.addWidget(empty)
        for row in column.rows:
            card = EmployeeCardWidget(row)
            card.clicked.connect(self.employee_activated.emit)
            cards.addWidget(card)
        cards.addStretch(1)
        outer.addLayout(cards)
        return box
