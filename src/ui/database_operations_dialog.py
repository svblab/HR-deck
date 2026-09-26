"""Единый диалог «Работа с базой данных» (EPIC-021)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from data.db import Connection
from domain.permissions import Permission, RoleCode, has_permission
from services.backup import BackupService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.session import SessionState
from services.status_history import StatusHistoryService
from ui.backup_dialog import BackupOperationsWidget
from ui.conversion_wizard_dialog import run_conversion_wizard_flow

OnRestored = Callable[[Connection], None]
OnDataChanged = Callable[[], None]


def can_open_database_operations(session: SessionState) -> bool:
    """Точка входа: Наблюдатель — нет; HR и Администратор — IMPORT_EXPORT."""
    return has_permission(session.role, Permission.IMPORT_EXPORT)


def database_operations_tab_visibility(session: SessionState) -> dict[str, bool]:
    """Видимость вкладок по ROADMAP EPIC-021 (без изменения матрицы прав)."""
    role = session.role if isinstance(session.role, RoleCode) else RoleCode(session.role)
    can_io = has_permission(role, Permission.IMPORT_EXPORT)
    # HR: все вкладки кроме «Резервное копирование»; Администратор — все.
    show_backup = role is RoleCode.ADMINISTRATOR
    return {
        "conversion": can_io,
        "import": can_io,
        "backup": show_backup,
    }


class DatabaseOperationsDialog(QDialog):
    """Shell: конвертация, transport-import (placeholder), резервное копирование."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        backup: BackupService,
        employees: EmployeeService,
        directories: DirectoryService,
        status_history: StatusHistoryService | None = None,
        on_restored: OnRestored | None = None,
        on_data_changed: OnDataChanged | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._session = session
        self._employees = employees
        self._directories = directories
        self._status_history = status_history
        self._on_data_changed = on_data_changed
        self._tabs_visibility = database_operations_tab_visibility(session)
        self.setObjectName("databaseOperationsDialog")
        self.setWindowTitle("Работа с базой данных")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setMinimumHeight(320)

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget(objectName="databaseOperationsTabs")
        layout.addWidget(self._tabs, stretch=1)

        if self._tabs_visibility["conversion"]:
            self._tabs.addTab(
                self._build_conversion_tab(),
                "Конвертация данных",
            )
        if self._tabs_visibility["import"]:
            self._tabs.addTab(
                self._build_import_placeholder_tab(),
                "Импорт данных",
            )
        if self._tabs_visibility["backup"]:
            backup_tab = QWidget(objectName="databaseOperationsBackupTab")
            backup_layout = QVBoxLayout(backup_tab)
            backup_layout.addWidget(
                BackupOperationsWidget(
                    backup,
                    session,
                    on_restored=on_restored,
                    restore_closes_dialog=False,
                    parent=backup_tab,
                )
            )
            backup_layout.addStretch(1)
            self._tabs.addTab(backup_tab, "Резервное копирование")

        close_btn = QPushButton("Закрыть", objectName="databaseOperationsCloseBtn")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)

    def _build_conversion_tab(self) -> QWidget:
        tab = QWidget(objectName="databaseOperationsConversionTab")
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(
            QLabel(
                "Построчная конвертация сотрудников из XLSX/CSV (EPIC-018, ADR-0012). "
                "Выберите файл и пройдите визард."
            )
        )
        btn = QPushButton("Начать конвертацию…", objectName="databaseOperationsConversionBtn")
        btn.clicked.connect(self._start_conversion)
        tab_layout.addWidget(btn)
        tab_layout.addStretch(1)
        return tab

    def _build_import_placeholder_tab(self) -> QWidget:
        tab = QWidget(objectName="databaseOperationsImportTab")
        tab_layout = QVBoxLayout(tab)
        tab_layout.addWidget(
            QLabel(
                "Приём transport-пакетов между установками (EPIC-020) будет доступен "
                "в следующих срезах. Сервисный слой уже на месте; UI подтверждения "
                "пакета здесь пока не реализован."
            )
        )
        tab_layout.addStretch(1)
        return tab

    def _start_conversion(self) -> None:
        if run_conversion_wizard_flow(
            self,
            self._conn,
            self._session,
            self._employees,
            self._directories,
            status_history=self._status_history,
        ):
            if self._on_data_changed is not None:
                self._on_data_changed()


__all__ = [
    "DatabaseOperationsDialog",
    "can_open_database_operations",
    "database_operations_tab_visibility",
]
