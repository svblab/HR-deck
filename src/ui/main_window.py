"""Главное окно: оболочка, сессия и главный экран (доска/таблица)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from data.db import Connection
from domain.permissions import Permission
from services.account_management import AccountManagementService
from services.authentication import AuthenticationService
from services.authorization import AuthorizationService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.roster import RosterService
from services.session import SessionState
from services.standard_reports import StandardReportService
from ui.auth_dialogs import AccountsDialog, UnlockDialog
from ui.roster_panel import RosterPanel
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

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        conn: Connection | None = None,
        session: SessionState | None = None,
        db_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Учёт доступности персонала")
        self.setStyleSheet(APP_STYLESHEET)
        self._conn = conn
        self._session = session
        self._db_path = db_path
        self._authz = AuthorizationService()
        self._auth = AuthenticationService()
        self._roster: RosterPanel | None = None

        root = QWidget(objectName="centralRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_title_bar())
        if self._conn is not None and self._session is not None:
            roster_service = RosterService(self._conn, self._session)
            self._roster = RosterPanel(
                roster_service,
                employees=EmployeeService(self._conn, self._session),
                directories=DirectoryService(self._conn, self._session),
                session=self._session,
                reports=StandardReportService(self._conn, self._session),
            )
            self._roster.filters_reset.connect(self._clear_search)
            self._search.setEnabled(True)
            self._search.textChanged.connect(self._roster.set_name_query)
            root_layout.addWidget(self._roster, stretch=1)
        else:
            root_layout.addWidget(self._build_toolbar())
            root_layout.addWidget(self._build_content_placeholder(), stretch=1)

        self.setCentralWidget(root)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._tick_clock()
        self._clock_timer.start()

        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(5_000)
        self._idle_timer.timeout.connect(self._check_idle)
        if self._session is not None:
            self._idle_timer.start()

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
        self._search = QLineEdit(objectName="searchInput")
        self._search.setPlaceholderText("Поиск сотрудника по ФИО...")
        self._search.setEnabled(False)
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(280)
        self._search.setMaximumWidth(340)
        layout.addWidget(self._search)
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

        if self._session is not None:
            user_label = QLabel(f"{self._session.login} ({self._session.role.value})")
            user_label.setObjectName("clockDate")
            right.addWidget(user_label)

        self._accounts_btn = QToolButton(objectName="titleIconBtn")
        self._accounts_btn.setText("👤")
        self._accounts_btn.setToolTip("Учётные записи")
        can_manage = (
            self._session is not None
            and self._authz.check(self._session.role, Permission.MANAGE_ACCOUNTS)
        )
        self._accounts_btn.setVisible(can_manage)
        self._accounts_btn.setEnabled(can_manage)
        self._accounts_btn.clicked.connect(self._open_accounts)

        settings_btn = QToolButton(objectName="titleIconBtn")
        settings_btn.setText("⚙")
        settings_btn.setToolTip("Настройки")
        settings_btn.setEnabled(False)
        exit_btn = QToolButton(objectName="titleIconBtn")
        exit_btn.setText("⏻")
        exit_btn.setToolTip("Выход")
        exit_btn.clicked.connect(self._logout_and_close)
        right.addWidget(self._accounts_btn)
        right.addWidget(settings_btn)
        right.addWidget(exit_btn)
        layout.addLayout(right)
        return bar

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget(objectName="toolbar")
        row = QHBoxLayout(toolbar)
        add_btn = QPushButton("+ Добавить сотрудника", objectName="primaryBtn")
        add_btn.setEnabled(False)
        row.addWidget(add_btn)
        return toolbar

    def _build_content_placeholder(self) -> QWidget:
        area = QWidget()
        layout = QVBoxLayout(area)
        label = QLabel("Войдите, чтобы открыть доску и таблицу.")
        label.setObjectName("contentPlaceholder")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return area

    def _clear_search(self) -> None:
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)

    def _tick_clock(self) -> None:
        time_text, date_text = format_clock()
        self._clock_time.setText(time_text)
        self._clock_date.setText(date_text)

    def _check_idle(self) -> None:
        if self._session is None or self._db_path is None:
            return
        if self._session.check_inactivity():
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self._conn = None
            dlg = UnlockDialog(self._session, self._db_path, self, conn=self._conn)
            if dlg.exec() != UnlockDialog.DialogCode.Accepted:
                self.close()
                return
            self._conn = dlg.conn

    def _open_accounts(self) -> None:
        if self._session is None or self._conn is None or self._db_path is None:
            return
        try:
            self._session.require_unlocked()
        except Exception:
            self._check_idle()
            return
        service = AccountManagementService(
            self._conn,
            self._session,
            db_path=self._db_path,
        )
        AccountsDialog(service, self).exec()

    def _logout_and_close(self) -> None:
        if self._session is not None and self._conn is not None:
            try:
                self._auth.logout(self._session, self._conn)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Выход", str(exc))
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
        self.close()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._session is not None and not self._session.locked:
            self._session.touch()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._session is not None and not self._session.locked:
            self._session.touch()
        super().keyPressEvent(event)
