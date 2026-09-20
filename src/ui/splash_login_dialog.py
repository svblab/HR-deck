"""Полноэкранная заставка входа с splash.png (Issue #85)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.auth_dialogs import LoginDialog
from ui.splash_assets import load_splash_pixmap, scale_splash_pixmap
from ui.theme import ACCENT, CARD, NAVY, TEXT, TEXT_MUTED


class SplashLoginDialog(LoginDialog):
    """Полноэкранный вход при старте; контракт conn/session как у LoginDialog."""

    def __init__(self, db_path: Path, parent: QWidget | None = None) -> None:
        QDialog.__init__(self, parent)
        self.setObjectName("splashLoginDialog")
        self.setWindowTitle("Вход")
        self._db_path = db_path
        self.conn = None
        self.session = None
        from services.authentication import AuthenticationService

        self._auth = AuthenticationService()

        self._splash_label = QLabel(objectName="splashLoginImage")
        self._splash_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._source_pixmap = load_splash_pixmap()
        self._splash_label.setVisible(not self._source_pixmap.isNull())

        self._login = QLineEdit(objectName="splashLoginUsername")
        self._password = QLineEdit(objectName="splashLoginPassword")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)

        root = QWidget(objectName="splashLoginRoot")
        root.setStyleSheet(f"background: {NAVY}; color: #ffffff;")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(48)

        layout.addWidget(self._splash_label, stretch=3)

        form_panel = QWidget(objectName="splashLoginForm")
        form_panel.setStyleSheet(
            f"background: {CARD}; color: {TEXT}; border-radius: 12px; padding: 8px;"
        )
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(32, 32, 32, 32)
        form_layout.setSpacing(18)

        title = QLabel("Журнал доступности персонала", objectName="splashLoginAppName")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        subtitle = QLabel("Вход в систему", objectName="splashLoginSubtitle")
        subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        form_layout.addWidget(title)
        form_layout.addWidget(subtitle)

        fields = QFormLayout()
        fields.setSpacing(12)
        fields.addRow("Логин", self._login)
        fields.addRow("Пароль", self._password)
        form_layout.addLayout(fields)

        recover_btn = QPushButton("Восстановление…", objectName="splashLoginRecoverBtn")
        recover_btn.setFlat(True)
        recover_btn.setStyleSheet(f"color: {ACCENT}; text-align: left;")
        recover_btn.clicked.connect(self._recover)
        form_layout.addWidget(recover_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_btn is not None:
            ok_btn.setText("Войти")
            ok_btn.setObjectName("splashLoginSubmitBtn")
        if cancel_btn is not None:
            cancel_btn.setText("Отмена")
            cancel_btn.setObjectName("splashLoginCancelBtn")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        form_layout.addWidget(buttons)

        layout.addWidget(form_panel, stretch=2)
        self._refresh_splash_image()

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self.showFullScreen()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_splash_image()

    def _refresh_splash_image(self) -> None:
        if self._source_pixmap.isNull():
            self._splash_label.clear()
            self._splash_label.setVisible(False)
            return
        max_w = max(1, int(self._splash_label.width() * 0.95))
        max_h = max(1, int(self.height() * 0.75))
        scaled = scale_splash_pixmap(self._source_pixmap, max_w, max_h)
        self._splash_label.setPixmap(scaled)
        self._splash_label.setVisible(not scaled.isNull())
