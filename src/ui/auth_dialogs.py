"""Диалоги входа, первичной настройки, разблокировки и учёток (без бизнес-правил)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from data.db import Connection
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationError, AuthenticationService
from services.bootstrap import BootstrapError, BootstrapService
from services.session import SessionState


class SetupDialog(QDialog):
    def __init__(self, db_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Первичная настройка")
        self._db_path = db_path
        self.conn: Connection | None = None
        self.session: SessionState | None = None
        self.recovery_code: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Создайте учётную запись Администратора. Резервный код будет показан один раз.")
        )
        form = QFormLayout()
        self._login = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password2 = QLineEdit()
        self._password2.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Логин", self._login)
        form.addRow("Пароль", self._password)
        form.addRow("Повтор пароля", self._password2)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._submit)
        layout.addWidget(buttons)

    def _submit(self) -> None:
        if self._password.text() != self._password2.text():
            QMessageBox.warning(self, "Ошибка", "Пароли не совпадают.")
            return
        try:
            conn, session, code = BootstrapService().initial_administrator_setup(
                db_path=self._db_path,
                login=self._login.text(),
                password=self._password.text(),
            )
        except BootstrapError as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return
        self.conn = conn
        self.session = session
        self.recovery_code = code
        dlg = RecoveryCodeDialog(code, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            QMessageBox.warning(
                self,
                "Требуется подтверждение",
                "Необходимо подтвердить сохранение резервного кода.",
            )
            return
        self.accept()


class RecoveryCodeDialog(QDialog):
    def __init__(self, code: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Резервный код восстановления")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Сохраните код вне программы. Он больше не будет показан в обычном интерфейсе."
            )
        )
        code_label = QLabel(code)
        code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        code_label.setStyleSheet("font-family: monospace; font-size: 16px;")
        layout.addWidget(code_label)
        self._confirm = QCheckBox("Я сохранил(а) резервный код")
        layout.addWidget(self._confirm)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._accept)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if not self._confirm.isChecked():
            QMessageBox.warning(self, "Подтверждение", "Отметьте, что код сохранён.")
            return
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, db_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Вход")
        self._db_path = db_path
        self.conn: Connection | None = None
        self.session: SessionState | None = None
        self._auth = AuthenticationService()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._login = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Логин", self._login)
        form.addRow("Пароль", self._password)
        layout.addLayout(form)
        row = QHBoxLayout()
        recover_btn = QPushButton("Восстановление…")
        recover_btn.clicked.connect(self._recover)
        row.addWidget(recover_btn)
        row.addStretch()
        layout.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _submit(self) -> None:
        try:
            conn, session = self._auth.login(
                db_path=self._db_path,
                login=self._login.text().strip(),
                password=self._password.text(),
            )
        except AuthenticationError:
            QMessageBox.warning(self, "Вход", "Неверный логин или пароль.")
            return
        self.conn = conn
        self.session = session
        self.accept()

    def _recover(self) -> None:
        dlg = RecoverPasswordDialog(self._db_path, self)
        dlg.exec()


class RecoverPasswordDialog(QDialog):
    def __init__(self, db_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Восстановление пароля Администратора")
        self._db_path = db_path
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._code = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password2 = QLineEdit()
        self._password2.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Резервный код", self._code)
        form.addRow("Новый пароль", self._password)
        form.addRow("Повтор пароля", self._password2)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._submit)
        layout.addWidget(buttons)

    def _submit(self) -> None:
        if self._password.text() != self._password2.text():
            QMessageBox.warning(self, "Ошибка", "Пароли не совпадают.")
            return
        try:
            new_code = BootstrapService().recover_administrator_password(
                db_path=self._db_path,
                recovery_code=self._code.text().strip(),
                new_password=self._password.text(),
            )
        except BootstrapError:
            QMessageBox.warning(self, "Восстановление", "Неверный или уже использованный код.")
            return
        dlg = RecoveryCodeDialog(new_code, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            QMessageBox.warning(
                self,
                "Требуется подтверждение",
                "Подтвердите сохранение нового резервного кода.",
            )
            return
        QMessageBox.information(self, "Готово", "Пароль Администратора обновлён. Войдите снова.")
        self.accept()


class UnlockDialog(QDialog):
    def __init__(
        self,
        session: SessionState,
        conn: Connection,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сессия заблокирована")
        self.setModal(True)
        self._session = session
        self._conn = conn
        self._auth = AuthenticationService()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Введите пароль для «{session.login}»"))
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._password)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._submit)
        layout.addWidget(buttons)

    def _submit(self) -> None:
        try:
            self._auth.unlock(self._session, self._conn, self._password.text())
        except AuthenticationError:
            QMessageBox.warning(self, "Разблокировка", "Неверный пароль.")
            return
        self.accept()


class AccountsDialog(QDialog):
    def __init__(
        self,
        service: AccountManagementService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Учётные записи")
        self._service = service
        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["ID", "Логин", "Роль", "Активна"])
        layout.addWidget(self._table)

        form = QFormLayout()
        self._login = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._role = QComboBox()
        for role in RoleCode:
            self._role.addItem(role.value, role)
        form.addRow("Логин", self._login)
        form.addRow("Пароль", self._password)
        form.addRow("Роль", self._role)
        layout.addLayout(form)

        create_btn = QPushButton("Создать")
        create_btn.clicked.connect(self._create)
        layout.addWidget(create_btn)

        settings_box = QFormLayout()
        self._timeout = QSpinBox()
        self._timeout.setRange(0, 86_400)
        self._timeout_enabled = QCheckBox("Включена")
        self._delay = QSpinBox()
        self._delay.setRange(0, 300)
        self._delay_enabled = QCheckBox("Включена")
        settings_box.addRow("Таймаут бездействия (сек)", self._timeout)
        settings_box.addRow("Автоблокировка", self._timeout_enabled)
        settings_box.addRow("Задержка после ошибки входа (сек)", self._delay)
        settings_box.addRow("Задержка", self._delay_enabled)
        layout.addLayout(settings_box)
        save_settings = QPushButton("Сохранить настройки безопасности")
        save_settings.clicked.connect(self._save_settings)
        layout.addWidget(save_settings)

        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(self.reject)
        close_btn.accepted.connect(self.accept)
        layout.addWidget(close_btn)

        self._reload()

    def _reload(self) -> None:
        rows = self._service.list_accounts()
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(str(row.id)))
            self._table.setItem(i, 1, QTableWidgetItem(row.login))
            self._table.setItem(i, 2, QTableWidgetItem(row.role_code))
            self._table.setItem(i, 3, QTableWidgetItem("да" if row.is_active else "нет"))
        settings = self._service.get_security_settings()
        self._timeout.setValue(int(settings["inactivity_timeout_seconds"]))
        self._timeout_enabled.setChecked(bool(settings["inactivity_timeout_enabled"]))
        self._delay.setValue(int(settings["login_failure_delay_seconds"]))
        self._delay_enabled.setChecked(bool(settings["login_failure_delay_enabled"]))

    def _create(self) -> None:
        role = self._role.currentData()
        try:
            self._service.create_account(
                login=self._login.text(),
                password=self._password.text(),
                role=role,
            )
        except Exception as exc:  # noqa: BLE001 — показать пользователю
            QMessageBox.warning(self, "Учётные записи", str(exc))
            return
        self._login.clear()
        self._password.clear()
        self._reload()

    def _save_settings(self) -> None:
        try:
            self._service.update_security_settings(
                inactivity_timeout_seconds=self._timeout.value(),
                inactivity_timeout_enabled=self._timeout_enabled.isChecked(),
                login_failure_delay_seconds=self._delay.value(),
                login_failure_delay_enabled=self._delay_enabled.isChecked(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Настройки", str(exc))
            return
        QMessageBox.information(self, "Настройки", "Сохранено.")
