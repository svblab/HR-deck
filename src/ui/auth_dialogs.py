"""Диалоги входа, первичной настройки, разблокировки и учёток (без бизнес-правил)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
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
from services.account_management import AccountManagementService, AccountView
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
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_btn is not None:
            ok_btn.setText("Войти")
        if cancel_btn is not None:
            cancel_btn.setText("Отмена")
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
        db_path: Path,
        parent: QWidget | None = None,
        *,
        conn: Connection | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сессия заблокирована")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._session = session
        self._db_path = db_path
        self._conn = conn
        self.conn: Connection | None = conn
        self._auth = AuthenticationService()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Введите пароль для «{session.login}»"))
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._password)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._submit)
        layout.addWidget(buttons)
        self._password.setFocus()

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self._password.setFocus()
        self._password.selectAll()

    def _submit(self) -> None:
        try:
            self.conn = self._auth.unlock(
                self._session,
                self._password.text(),
                db_path=self._db_path,
                conn=self._conn,
            )
        except AuthenticationError:
            QMessageBox.warning(self, "Разблокировка", "Неверный пароль.")
            return
        self.accept()


class _ResetPasswordDialog(QDialog):
    def __init__(self, login: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сброс пароля")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Новый пароль для «{login}»"))
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._password)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class AccountsDialog(QDialog):
    def __init__(
        self,
        service: AccountManagementService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Учётные записи")
        self._service = service
        self._acting_id = service.acting_account_id
        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["ID", "Логин", "Роль", "Активна", "Действия"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)

        form = QFormLayout()
        self._login = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._role = QComboBox()
        for role in (RoleCode.HR_EMPLOYEE, RoleCode.OBSERVER):
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
            self._table.setCellWidget(i, 4, self._actions_widget(row))
        settings = self._service.get_security_settings()
        self._timeout.setValue(int(settings["inactivity_timeout_seconds"]))
        self._timeout_enabled.setChecked(bool(settings["inactivity_timeout_enabled"]))
        self._delay.setValue(int(settings["login_failure_delay_seconds"]))
        self._delay_enabled.setChecked(bool(settings["login_failure_delay_enabled"]))

    def _actions_widget(self, row: AccountView) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        is_admin = row.role_code == RoleCode.ADMINISTRATOR.value
        is_self = row.id == self._acting_id
        can_edit_role = not is_admin and not is_self
        role_combo = QComboBox(objectName=f"accountRoleCombo_{row.id}")
        for role in (RoleCode.HR_EMPLOYEE, RoleCode.OBSERVER):
            role_combo.addItem(role.value, role.value)
        idx = role_combo.findData(row.role_code)
        if idx >= 0:
            role_combo.setCurrentIndex(idx)
        role_combo.setEnabled(can_edit_role)
        apply_btn = QPushButton("Применить", objectName=f"accountApplyRoleBtn_{row.id}")
        apply_btn.setEnabled(can_edit_role)
        apply_btn.clicked.connect(
            lambda _checked=False, account_id=row.id, combo=role_combo: self._apply_role(
                account_id, combo
            )
        )
        archive_btn = QPushButton(
            "Восстановить" if not row.is_active else "Архивировать",
            objectName=f"accountToggleActiveBtn_{row.id}",
        )
        archive_btn.setEnabled(not is_self and not (is_admin and row.is_active))
        archive_btn.clicked.connect(
            lambda _checked=False, account_id=row.id: self._toggle_active(account_id)
        )
        reset_btn = QPushButton(
            "Сбросить пароль", objectName=f"accountResetPasswordBtn_{row.id}"
        )
        reset_btn.clicked.connect(
            lambda _checked=False, account_id=row.id, login=row.login: self._reset_password(
                account_id, login
            )
        )
        layout.addWidget(role_combo)
        layout.addWidget(apply_btn)
        layout.addWidget(archive_btn)
        layout.addWidget(reset_btn)
        return box

    def _apply_role(self, account_id: int, combo: QComboBox) -> None:
        role = combo.currentData()
        try:
            self._service.set_role(account_id, role)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Учётные записи", str(exc))
            return
        self._reload()

    def _toggle_active(self, account_id: int) -> None:
        row = next(r for r in self._service.list_accounts() if r.id == account_id)
        try:
            self._service.set_active(account_id, not row.is_active)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Учётные записи", str(exc))
            return
        self._reload()

    def _reset_password(self, account_id: int, login: str) -> None:
        dlg = _ResetPasswordDialog(login, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._service.reset_password(account_id, dlg._password.text())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Учётные записи", str(exc))
            return
        QMessageBox.information(self, "Учётные записи", "Пароль обновлён.")
        self._reload()

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
