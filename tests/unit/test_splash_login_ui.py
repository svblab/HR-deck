"""UI: полноэкранная заставка входа (Issue #85)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QMessageBox

from domain.permissions import RoleCode
from services.authentication import AuthenticationError, AuthenticationService
from services.bootstrap import BootstrapService
from ui.auth_dialogs import RecoverPasswordDialog
from ui.splash_assets import SPLASH_IMAGE_RESOURCE, load_splash_pixmap, scale_splash_pixmap
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


def test_scale_splash_pixmap_preserves_aspect_ratio(qapp) -> None:  # noqa: ANN001
    source = load_splash_pixmap()
    assert not source.isNull()
    ratio = source.width() / source.height()
    scaled = scale_splash_pixmap(source, max_width=400, max_height=300)
    assert not scaled.isNull()
    assert scaled.width() <= 400
    assert scaled.height() <= 300
    assert abs(scaled.width() / scaled.height() - ratio) < 0.02


def test_splash_login_dialog_builds_form(qtbot, tmp_path: Path) -> None:
    dlg = SplashLoginDialog(tmp_path / "missing.db")
    qtbot.addWidget(dlg)

    assert dlg.findChild(QLineEdit, "splashLoginUsername") is not None
    assert dlg.findChild(QLineEdit, "splashLoginPassword") is not None
    assert dlg.objectName() == "splashLoginDialog"
    assert not dlg._source_pixmap.isNull()
    assert dlg.findChild(QLabel, "splashLoginImage") is not None


def test_splash_login_dialog_hides_image_when_unavailable(
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

    image = dlg.findChild(QLabel, "splashLoginImage")
    assert image is not None
    assert not image.isVisible()


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
