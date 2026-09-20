"""Smoke-тесты загрузки встроенной иконки приложения."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog

from ui.app_icon import (
    app_icon_path,
    apply_app_window_icon,
    install_app_window_icon,
    load_app_icon,
)


def test_app_icon_asset_exists() -> None:
    assert app_icon_path().is_file()


def test_load_app_icon_is_not_empty(qapp: QApplication) -> None:
    icon = load_app_icon()
    assert not icon.isNull()


def test_install_and_apply_window_icon(qapp: QApplication) -> None:
    icon = install_app_window_icon(qapp)
    assert not icon.isNull()
    assert not qapp.windowIcon().isNull()

    dialog = QDialog()
    apply_app_window_icon(dialog)
    assert not dialog.windowIcon().isNull()
