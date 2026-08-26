"""Точка входа приложения."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def run() -> int:
    """Создать QApplication и показать главное окно. Возвращает код выхода."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Журнал доступности персонала")
    app.setOrganizationName("HR")
    window = MainWindow()
    window.showFullScreen()
    return app.exec()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
