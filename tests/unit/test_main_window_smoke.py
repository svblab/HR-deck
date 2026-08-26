"""Смоук оболочки главного окна (EPIC-001): запуск без бизнес-логики."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QWidget

from ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.mark.acceptance
def test_main_window_builds_shell(qapp: QApplication) -> None:
    """ТЗ §11 «установка и запуск»: окно создаётся с логотипом, часами и панелью."""
    window = MainWindow()
    assert window.windowTitle() == "Учёт доступности персонала"
    assert window.centralWidget() is not None

    logo = window.findChild(QLabel, "logoBadge")
    assert logo is not None
    assert logo.text() == "ЛОГО"

    clock_time = window.findChild(QLabel, "clockTime")
    assert clock_time is not None
    assert ":" in clock_time.text()

    clock_date = window.findChild(QLabel, "clockDate")
    assert clock_date is not None
    assert clock_date.text() not in {"", "--"}

    search = window.findChild(QLineEdit, "searchInput")
    assert search is not None
    assert not search.isEnabled()

    add_btn = window.findChild(QPushButton, "primaryBtn")
    assert add_btn is not None
    assert not add_btn.isEnabled()

    assert window.findChild(QWidget, "titleBar") is not None
    assert window.findChild(QWidget, "toolbar") is not None

    window.close()
