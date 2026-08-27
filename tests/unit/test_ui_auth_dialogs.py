"""Widget-level smoke tests for auth dialogs (password / recovery-code path)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox

from services.authentication import AuthenticationError
from ui.auth_dialogs import LoginDialog, RecoveryCodeDialog, SetupDialog


def _capture_warnings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    seen: list[tuple[object, ...]] = []

    def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warning)  # type: ignore[attr-defined]
    return seen


def test_setup_dialog_mismatched_passwords_do_not_proceed(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings = _capture_warnings(monkeypatch)
    called: list[str] = []

    class StubBootstrap:
        def initial_administrator_setup(self, **_kwargs: object) -> None:
            called.append("setup")
            raise AssertionError("setup must not run when passwords differ")

    monkeypatch.setattr("ui.auth_dialogs.BootstrapService", StubBootstrap)

    dlg = SetupDialog(tmp_path / "app.db")
    qtbot.addWidget(dlg)
    dlg._login.setText("admin")
    dlg._password.setText("one")
    dlg._password2.setText("two")
    dlg._submit()

    assert not called
    assert dlg.result() != QDialog.DialogCode.Accepted
    assert any("Пароли не совпадают" in str(item) for item in warnings)


def test_recovery_code_dialog_refuses_without_checkbox(qtbot, monkeypatch) -> None:
    warnings = _capture_warnings(monkeypatch)
    dlg = RecoveryCodeDialog("SECRET-CODE-1")
    qtbot.addWidget(dlg)
    dlg.show()

    labels = [w.text() for w in dlg.findChildren(QLabel)]
    assert "SECRET-CODE-1" in labels

    dlg._accept()
    assert dlg.result() != QDialog.DialogCode.Accepted
    assert dlg.isVisible()
    assert any("Отметьте" in str(item) for item in warnings)

    dlg._confirm.setChecked(True)
    dlg._accept()
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_setup_dialog_success_shows_recovery_code_and_requires_checkbox(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings = _capture_warnings(monkeypatch)

    class StubBootstrap:
        def initial_administrator_setup(self, **_kwargs: object) -> tuple[object, object, str]:
            return object(), object(), "RECOVERY-PLAINTEXT"

    monkeypatch.setattr("ui.auth_dialogs.BootstrapService", StubBootstrap)

    seen_labels: list[str] = []

    def _interact() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, RecoveryCodeDialog) and widget.isVisible():
                seen_labels.extend(w.text() for w in widget.findChildren(QLabel))
                widget._accept()
                assert widget.isVisible()
                widget._confirm.setChecked(True)
                widget._accept()
                return

    dlg = SetupDialog(tmp_path / "app.db")
    qtbot.addWidget(dlg)
    dlg._login.setText("admin")
    dlg._password.setText("AdminPass-1")
    dlg._password2.setText("AdminPass-1")
    QTimer.singleShot(0, _interact)
    dlg._submit()

    assert "RECOVERY-PLAINTEXT" in seen_labels
    assert dlg.recovery_code == "RECOVERY-PLAINTEXT"
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert any("Отметьте" in str(item) for item in warnings)


def test_login_dialog_failed_login_generic_error(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings = _capture_warnings(monkeypatch)

    class StubAuth:
        def login(self, **_kwargs: object) -> None:
            raise AuthenticationError("invalid credentials")

    dlg = LoginDialog(tmp_path / "app.db")
    qtbot.addWidget(dlg)
    dlg._auth = StubAuth()  # type: ignore[assignment]
    dlg._login.setText("admin")
    dlg._password.setText("wrong-password")
    dlg._submit()

    assert dlg.result() != QDialog.DialogCode.Accepted
    texts = " ".join(str(item) for item in warnings)
    assert "Неверный логин или пароль." in texts
    assert "invalid credentials" not in texts
    assert "wrong-password" not in texts
