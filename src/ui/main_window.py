"""Главное окно: оболочка из HTML-прототипа без бизнес-логики (EPIC-001)."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import APP_STYLESHEET

_MONTHS_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def format_clock(now: datetime | None = None) -> tuple[str, str]:
    """Вернуть (время HH:MM:SS, дата «день недели, DD месяц YYYY») как в прототипе."""
    now = now or datetime.now()
    time_text = now.strftime("%H:%M:%S")
    date_text = (
        f"{_WEEKDAYS_RU[now.weekday()]}, {now.day:02d} {_MONTHS_RU[now.month]} {now.year}"
    )
    return time_text, date_text


class MainWindow(QMainWindow):
    """Полноэкранная оболочка: логотип, поиск-заглушка, часы, панель управления."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Учёт доступности персонала")
        self.setStyleSheet(APP_STYLESHEET)

        root = QWidget(objectName="centralRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_title_bar())
        root_layout.addWidget(self._build_toolbar())
        root_layout.addWidget(self._build_content_placeholder(), stretch=1)

        self.setCentralWidget(root)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._tick_clock()
        self._clock_timer.start()

    def _build_title_bar(self) -> QWidget:
        bar = QWidget(objectName="titleBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(18)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        logo = QLabel("ЛОГО", objectName="logoBadge")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        company = QLabel("Название компании", objectName="brandCompany")
        app_name = QLabel("Учёт доступности персонала", objectName="brandApp")
        brand_text.addWidget(company)
        brand_text.addWidget(app_name)
        brand.addWidget(logo)
        brand.addLayout(brand_text)
        layout.addLayout(brand)

        layout.addStretch(1)
        search = QLineEdit(objectName="searchInput")
        search.setPlaceholderText("Поиск сотрудника по ФИО...")
        search.setEnabled(False)  # бизнес-логика — EPIC-008
        search.setClearButtonEnabled(False)
        search.setMinimumWidth(280)
        search.setMaximumWidth(340)
        layout.addWidget(search)
        layout.addStretch(1)

        right = QHBoxLayout()
        right.setSpacing(18)
        clock_box = QVBoxLayout()
        clock_box.setSpacing(0)
        clock_box.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._clock_time = QLabel("--:--:--", objectName="clockTime")
        self._clock_time.setAlignment(Qt.AlignmentFlag.AlignRight)
        mono = QFont(self._clock_time.font())
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._clock_time.setFont(mono)
        self._clock_date = QLabel("--", objectName="clockDate")
        self._clock_date.setAlignment(Qt.AlignmentFlag.AlignRight)
        clock_box.addWidget(self._clock_time)
        clock_box.addWidget(self._clock_date)
        right.addLayout(clock_box)

        settings_btn = QToolButton(objectName="titleIconBtn")
        settings_btn.setText("⚙")
        settings_btn.setToolTip("Настройки")
        settings_btn.setEnabled(False)
        exit_btn = QToolButton(objectName="titleIconBtn")
        exit_btn.setText("⏻")
        exit_btn.setToolTip("Выход")
        exit_btn.clicked.connect(self.close)
        right.addWidget(settings_btn)
        right.addWidget(exit_btn)
        layout.addLayout(right)
        return bar

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget(objectName="toolbar")
        outer = QVBoxLayout(toolbar)
        outer.setContentsMargins(20, 10, 20, 10)
        outer.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        add_btn = QPushButton("+ Добавить сотрудника", objectName="primaryBtn")
        add_btn.setEnabled(False)
        reports_btn = QPushButton("Отчёты")
        reports_btn.setEnabled(False)
        board_btn = QPushButton("Доска", objectName="viewToggleActive")
        board_btn.setEnabled(False)
        table_btn = QPushButton("Таблица", objectName="viewToggleInactive")
        table_btn.setEnabled(False)
        row1.addWidget(add_btn)
        row1.addWidget(reports_btn)
        row1.addWidget(board_btn)
        row1.addWidget(table_btn)
        row1.addStretch(1)
        summary = QLabel("Счётчики статусов — после EPIC-008")
        summary.setObjectName("contentPlaceholder")
        row1.addWidget(summary)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        for placeholder in ("Все филиалы", "Все департаменты", "Все отделы"):
            combo = QComboBox()
            combo.addItem(placeholder)
            combo.setEnabled(False)
            row2.addWidget(combo)
        reset = QPushButton("Показать всех", objectName="filterReset")
        reset.setEnabled(False)
        row2.addWidget(reset)
        row2.addStretch(1)
        outer.addLayout(row2)
        return toolbar

    def _build_content_placeholder(self) -> QWidget:
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(20, 18, 20, 18)
        label = QLabel(
            "Область доски/таблицы — заглушка EPIC-001.\n"
            "Данные и режимы появятся в EPIC-008."
        )
        label.setObjectName("contentPlaceholder")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(label)
        return area

    def _tick_clock(self) -> None:
        time_text, date_text = format_clock()
        self._clock_time.setText(time_text)
        self._clock_date.setText(date_text)
