"""Диалог резервного копирования и восстановления (EPIC-012)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from data.db import Connection
from domain.permissions import Permission, has_permission
from services.authorization import AuthorizationError
from services.backup import BackupError, BackupService
from services.session import SessionState

OnRestored = Callable[[Connection], None]


class BackupOperationsWidget(QWidget):
    """Панель создания/восстановления копии — в диалоге или вкладке EPIC-021."""

    def __init__(
        self,
        backup: BackupService,
        session: SessionState,
        *,
        on_restored: OnRestored | None = None,
        restore_closes_dialog: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._backup = backup
        self._session = session
        self._on_restored = on_restored
        self._restore_closes_dialog = restore_closes_dialog
        self._can_create = has_permission(session.role, Permission.CREATE_BACKUP)
        self._can_restore = has_permission(session.role, Permission.RESTORE_BACKUP)
        self.setObjectName("backupOperationsWidget")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            QLabel(
                "Резервная копия — зашифрованный файл базы и sidecar keywrap (ADR-0002). "
                "После создания копия проверяется автоматически."
            )
        )
        row = QHBoxLayout()
        self._create_btn = QPushButton("Создать копию…", objectName="backupCreateBtn")
        self._restore_btn = QPushButton("Восстановить…", objectName="backupRestoreBtn")
        self._create_btn.setEnabled(self._can_create)
        self._restore_btn.setEnabled(self._can_restore)
        self._create_btn.clicked.connect(self._create)
        self._restore_btn.clicked.connect(self._restore)
        row.addWidget(self._create_btn)
        row.addWidget(self._restore_btn)
        row.addStretch(1)
        layout.addLayout(row)
        self._status = QLabel(objectName="backupStatus")
        layout.addWidget(self._status)

    def _create(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Каталог для резервной копии")
        if not directory:
            return
        try:
            path = self._backup.create_backup(directory)
        except (BackupError, AuthorizationError) as exc:
            QMessageBox.warning(self, "Резервная копия", str(exc))
            return
        self._status.setText(f"Создано: {path}")

    def _restore(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл резервной копии",
            "",
            "Database (*.db);;All files (*)",
        )
        if not path_str:
            return
        answer = QMessageBox.warning(
            self,
            "Восстановление",
            "Текущая база данных будет заменена выбранной копией.\n"
            "Перед заменой будет создана автоматическая копия текущего состояния.\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            conn = self._backup.restore_backup(Path(path_str))
        except (BackupError, AuthorizationError) as exc:
            QMessageBox.critical(self, "Восстановление", str(exc))
            return
        if self._on_restored is not None:
            self._on_restored(conn)
        QMessageBox.information(
            self,
            "Восстановление",
            "База восстановлена и прошла проверку целостности.",
        )
        if self._restore_closes_dialog:
            dialog = self.window()
            if isinstance(dialog, QDialog):
                dialog.accept()


class BackupDialog(QDialog):
    def __init__(
        self,
        backup: BackupService,
        session: SessionState,
        *,
        on_restored: OnRestored | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("backupDialog")
        self.setWindowTitle("Резервное копирование")
        self.setModal(True)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        self._operations = BackupOperationsWidget(
            backup,
            session,
            on_restored=on_restored,
            restore_closes_dialog=True,
            parent=self,
        )
        layout.addWidget(self._operations)

    def _restore(self) -> None:
        """Test hook and legacy access to restore action."""
        self._operations._restore()
