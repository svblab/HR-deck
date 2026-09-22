"""Полноэкранная заставка входа с splash.png (Issue #85)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QResizeEvent
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
from ui.splash_assets import cover_splash_pixmap, load_splash_pixmap
from ui.theme import ACCENT, NAVY, TEXT, TEXT_MUTED


class _SplashLoginRoot(QWidget):
    """Корневой контейнер: фоновый слой + независимая форма поверх."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("splashLoginRoot")
        self._source_pixmap = QPixmap()

        self._background = QLabel(self)
        self._background.setObjectName("splashLoginBackground")
        self._background.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._overlay = QWidget(self)
        self._overlay.setObjectName("splashLoginOverlay")
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._overlay.setStyleSheet("background: transparent;")

        self._overlay_layout = QVBoxLayout(self._overlay)
        self._overlay_layout.setContentsMargins(32, 32, 32, 32)

    @property
    def background_label(self) -> QLabel:
        return self._background

    def set_source_pixmap(self, pixmap: QPixmap) -> None:
        self._source_pixmap = pixmap
        self._refresh_background()

    def set_foreground_form(self, form: QWidget, *, horizontal_bias: float) -> None:
        """Разместить форму поверх фона; bias 0.0 — слева, 0.5 — по центру, 1.0 — справа."""
        bias = min(1.0, max(0.0, horizontal_bias))
        left_stretch = max(1, int(bias * 20))
        right_stretch = max(1, int((1.0 - bias) * 20))

        self._overlay_layout.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(left_stretch)
        row.addWidget(form)
        row.addStretch(right_stretch)
        self._overlay_layout.addLayout(row)
        self._overlay_layout.addStretch(1)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        rect = self.rect()
        self._background.setGeometry(rect)
        self._overlay.setGeometry(rect)
        self._overlay.raise_()
        self._refresh_background()

    def _refresh_background(self) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        if self._source_pixmap.isNull():
            self._background.clear()
            self._background.setStyleSheet(f"background: {NAVY};")
            self.setStyleSheet(f"background: {NAVY};")
            return

        covered = cover_splash_pixmap(self._source_pixmap, width, height)
        self._background.setPixmap(covered)
        self._background.setStyleSheet("")
        self.setStyleSheet(f"background: {NAVY};")


class SplashLoginDialog(LoginDialog):
    """Полноэкранный вход при старте; контракт conn/session как у LoginDialog."""

    # Горизонтальное смещение формы: 0.5 — центр; уменьшить для сдвига влево.
    _FORM_HORIZONTAL_BIAS = 0.5

    def __init__(self, db_path: Path, parent: QWidget | None = None) -> None:
        QDialog.__init__(self, parent)
        self.setObjectName("splashLoginDialog")
        self.setWindowTitle("Вход")
        # Полноэкранный режим: флаг до первого show; сам переход — в showEvent.
        self.setWindowFlag(Qt.WindowType.Window, True)
        self._db_path = db_path
        self.conn = None
        self.session = None
        from services.authentication import AuthenticationService

        self._auth = AuthenticationService()

        self._source_pixmap = load_splash_pixmap()

        self._root = _SplashLoginRoot()
        self._background = self._root.background_label
        self._form_panel = self._build_form_panel()
        self._root.set_foreground_form(
            self._form_panel,
            horizontal_bias=self._FORM_HORIZONTAL_BIAS,
        )
        self._root.set_source_pixmap(self._source_pixmap)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._root)

    def _build_form_panel(self) -> QWidget:
        self._login = QLineEdit(objectName="splashLoginUsername")
        self._password = QLineEdit(objectName="splashLoginPassword")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)

        form_panel = QWidget(objectName="splashLoginForm")
        form_panel.setMaximumWidth(360)
        form_panel.setStyleSheet(
            "QWidget#splashLoginForm {"
            "  background: rgba(255, 255, 255, 0.78);"
            "  border: 1px solid rgba(255, 255, 255, 0.45);"
            "  border-radius: 10px;"
            f"  color: {TEXT};"
            "}"
        )

        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(28, 28, 28, 28)
        form_layout.setSpacing(16)

        subtitle = QLabel("Вход в систему", objectName="splashLoginSubtitle")
        subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        form_layout.addWidget(subtitle)

        fields = QFormLayout()
        fields.setSpacing(10)
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

        return form_panel

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        # Не вызывать showFullScreen() синхронно из showEvent: на Windows
        # это даёт рекурсию/зависание при первом показе диалога.
        if not self.isFullScreen():
            QTimer.singleShot(0, self._enter_fullscreen)

    def _enter_fullscreen(self) -> None:
        if not self.isFullScreen():
            self.showFullScreen()
