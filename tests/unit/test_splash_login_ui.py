"""UI: полноэкранная заставка входа (Issue #85)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QWidget

from domain.permissions import RoleCode
from services.authentication import AuthenticationError, AuthenticationService
from services.bootstrap import BootstrapService
from ui.auth_dialogs import RecoverPasswordDialog
from ui.splash_assets import SPLASH_IMAGE_RESOURCE, cover_splash_pixmap, load_splash_pixmap
from ui.splash_login_dialog import SplashLoginDialog


def _seed_db(tmp_path: Path) -> Path:
    db = tmp_path / "app.db"
    conn, _session, _code = BootstrapService().initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    conn.close()
    return db


def _capture_warnings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    seen: list[tuple[object, ...]] = []

    def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warning)  # type: ignore[attr-defined]
    return seen


def test_splash_image_available_from_qt_resources(qapp) -> None:  # noqa: ANN001
    pixmap = load_splash_pixmap()
    assert not pixmap.isNull()
    assert SPLASH_IMAGE_RESOURCE == ":/ui/Splash/splash.png"


def test_cover_splash_pixmap_fills_target_without_distortion(qapp) -> None:  # noqa: ANN001
    source = load_splash_pixmap()
    assert not source.isNull()
    source_ratio = source.width() / source.height()

    covered = cover_splash_pixmap(source, target_width=1280, target_height=720)
    assert not covered.isNull()
    assert covered.width() == 1280
    assert covered.height() == 720

    scale = max(1280 / source.width(), 720 / source.height())
    scaled_w = int(source.width() * scale + 0.5)
    scaled_h = int(source.height() * scale + 0.5)
    assert abs(scaled_w / scaled_h - source_ratio) < 0.02


def test_splash_login_dialog_uses_fullscreen_background_layer(qtbot, tmp_path: Path) -> None:
    dlg = SplashLoginDialog(tmp_path / "missing.db")
    qtbot.addWidget(dlg)
    dlg.resize(960, 540)
    dlg.show()
    qtbot.waitExposed(dlg)

    background = dlg.findChild(QLabel, "splashLoginBackground")
    overlay = dlg.findChild(QWidget, "splashLoginOverlay")  # type: ignore[name-defined]
    form = dlg.findChild(QWidget, "splashLoginForm")  # type: ignore[name-defined]

    assert background is not None
    assert overlay is not None
    assert form is not None
    assert dlg.findChild(QLabel, "splashLoginImage") is None
    assert background.geometry() == dlg._root.rect()
    assert overlay.geometry() == dlg._root.rect()
    assert not dlg._source_pixmap.isNull()
    pixmap = background.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.width() == dlg._root.width()
    assert pixmap.height() == dlg._root.height()


def test_splash_login_background_recalculates_on_resize(qtbot, tmp_path: Path) -> None:
    dlg = SplashLoginDialog(tmp_path / "missing.db")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    dlg.resize(800, 600)
    qtbot.wait(10)
    first = dlg.findChild(QLabel, "splashLoginBackground")
    assert first is not None
    pixmap_first = first.pixmap()
    assert pixmap_first is not None
    assert pixmap_first.width() == 800
    assert pixmap_first.height() == 600

    dlg.resize(1024, 768)
    qtbot.wait(10)
    pixmap_second = first.pixmap()
    assert pixmap_second is not None
    assert pixmap_second.width() == 1024
    assert pixmap_second.height() == 768


def test_splash_login_form_is_independent_foreground_component(
    qtbot, tmp_path: Path
) -> None:
    dlg = SplashLoginDialog(tmp_path / "missing.db")
    qtbot.addWidget(dlg)

    overlay = dlg.findChild(QWidget, "splashLoginOverlay")  # type: ignore[name-defined]
    form = dlg.findChild(QWidget, "splashLoginForm")  # type: ignore[name-defined]
    background = dlg.findChild(QLabel, "splashLoginBackground")

    assert overlay is not None and form is not None and background is not None
    assert form.parentWidget() is overlay
    assert background.parentWidget() is dlg._root
    assert form.parentWidget() is not background

    assert dlg.findChild(QLineEdit, "splashLoginUsername") is not None
    assert dlg.findChild(QLineEdit, "splashLoginPassword") is not None
    assert dlg.objectName() == "splashLoginDialog"


def test_splash_login_dialog_has_no_side_by_side_image_panel(
    qtbot, tmp_path: Path
) -> None:
    dlg = SplashLoginDialog(tmp_path / "missing.db")
    qtbot.addWidget(dlg)

    background = dlg.findChild(QLabel, "splashLoginBackground")
    form = dlg.findChild(QWidget, "splashLoginForm")  # type: ignore[name-defined]
    assert background is not None and form is not None

    for layout in (dlg.findChildren(QHBoxLayout),):
        for hbox in layout:
            direct_widgets = []
            for i in range(hbox.count()):
                item = hbox.itemAt(i)
                if item is not None and item.widget() is not None:
                    direct_widgets.append(item.widget())
            if background in direct_widgets and form in direct_widgets:
                pytest.fail("background and form must not share a horizontal content panel")


def test_splash_login_dialog_fallback_when_image_unavailable(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ui.splash_login_dialog.load_splash_pixmap",
        lambda: QPixmap(),
    )
    dlg = SplashLoginDialog(tmp_path / "missing.db")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    background = dlg.findChild(QLabel, "splashLoginBackground")
    form = dlg.findChild(QWidget, "splashLoginForm")  # type: ignore[name-defined]
    assert background is not None
    assert form is not None
    assert form.isVisible()
    assert background.pixmap() is None or background.pixmap().isNull()


def test_splash_login_dialog_success_returns_session(qtbot, tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    dlg = SplashLoginDialog(db)
    qtbot.addWidget(dlg)
    dlg._auth = AuthenticationService(sleeper=lambda _s: None)
    dlg._login.setText("admin")
    dlg._password.setText("AdminPass-1")
    dlg._submit()

    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.session is not None
    assert dlg.session.role == RoleCode.ADMINISTRATOR
    assert dlg.conn is not None
    dlg.conn.close()


def test_splash_login_dialog_invalid_credentials_use_existing_error_path(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings = _capture_warnings(monkeypatch)

    class StubAuth:
        def login(self, **_kwargs: object) -> None:
            raise AuthenticationError("invalid")

    dlg = SplashLoginDialog(tmp_path / "app.db")
    qtbot.addWidget(dlg)
    dlg._auth = StubAuth()  # type: ignore[assignment]
    dlg._login.setText("admin")
    dlg._password.setText("wrong")
    dlg._submit()

    assert dlg.result() != QDialog.DialogCode.Accepted
    texts = " ".join(str(item) for item in warnings)
    assert "Неверный логин или пароль." in texts


def test_splash_login_dialog_recovery_opens_existing_flow(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[RecoverPasswordDialog] = []

    def _track_exec(self: RecoverPasswordDialog) -> int:  # noqa: N805
        opened.append(self)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(RecoverPasswordDialog, "exec", _track_exec)

    dlg = SplashLoginDialog(tmp_path / "app.db")
    qtbot.addWidget(dlg)
    dlg._recover()

    assert len(opened) == 1
    assert opened[0].parent() is dlg


def test_splash_login_dialog_cancel_rejects(qtbot, tmp_path: Path) -> None:
    dlg = SplashLoginDialog(tmp_path / "app.db")
    qtbot.addWidget(dlg)
    dlg.reject()
    assert dlg.result() == QDialog.DialogCode.Rejected
    assert dlg.conn is None
    assert dlg.session is None


def test_app_startup_uses_splash_login_dialog(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui import app as app_module

    db = _seed_db(tmp_path)
    created: list[SplashLoginDialog] = []

    class StubSplash(SplashLoginDialog):
        def __init__(self, db_path: Path, parent=None) -> None:  # noqa: ANN001
            super().__init__(db_path, parent)
            created.append(self)
            self._auto_accept = True

        def exec(self) -> int:
            if self._auto_accept:
                self._auth = AuthenticationService(sleeper=lambda _s: None)
                self._login.setText("admin")
                self._password.setText("AdminPass-1")
                self._submit()
                return QDialog.DialogCode.Accepted
            return super().exec()

    monkeypatch.setattr(app_module, "SplashLoginDialog", StubSplash)
    monkeypatch.setattr(
        app_module.BootstrapService,
        "needs_setup",
        lambda self, _path: False,
    )
    monkeypatch.setattr(
        app_module.UpgradeService,
        "apply_pending",
        lambda self: None,
    )

    window_shown: list[object] = []

    class StubMainWindow:
        def __init__(self, **_kwargs: object) -> None:
            window_shown.append(self)

        def showFullScreen(self) -> None:
            pass

    monkeypatch.setattr(app_module, "MainWindow", StubMainWindow)
    monkeypatch.setattr(app_module, "install_session_activity_filter", lambda *_a, **_k: None)

    class StubApp:
        @staticmethod
        def instance() -> None:
            return None

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def exec(self) -> int:
            return 0

        def setApplicationName(self, *_args: object, **_kwargs: object) -> None:
            pass

        def setOrganizationName(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(app_module, "QApplication", StubApp)
    monkeypatch.setattr(app_module, "install_app_window_icon", lambda _app: None)

    with patch.object(app_module, "prepare_database_startup"):
        result = app_module.run(db_path=db)

    assert result == 0
    assert created
    assert window_shown
