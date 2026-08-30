"""Точка входа приложения: setup → login → главное окно."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from data.backup_io import DatabaseCorruptionError, prepare_database_startup
from data.paths import default_db_path
from services.bootstrap import BootstrapService
from services.upgrade import UpgradeError, UpgradeService
from ui.auth_dialogs import LoginDialog, SetupDialog
from ui.main_window import MainWindow


def run(db_path: Path | None = None) -> int:
    """Создать QApplication, пройти auth-flow и показать главное окно."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Журнал доступности персонала")
    app.setOrganizationName("HR")

    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        prepare_database_startup(path)
    except DatabaseCorruptionError as exc:
        QMessageBox.critical(
            None,
            "Повреждение базы данных",
            str(exc),
        )
        return 1

    conn = None
    session = None
    if BootstrapService().needs_setup(path):
        dlg = SetupDialog(path)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return 1
        conn, session = dlg.conn, dlg.session
    else:
        dlg = LoginDialog(path)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return 1
        conn, session = dlg.conn, dlg.session

    try:
        UpgradeService(conn, session, db_path=path).apply_pending()
    except UpgradeError as exc:
        QMessageBox.critical(
            None,
            "Обновление базы данных",
            f"{exc}\n\nПриложение будет закрыто.",
        )
        conn.close()
        return 1

    window = MainWindow(conn=conn, session=session, db_path=path)
    window.showFullScreen()
    return app.exec()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
