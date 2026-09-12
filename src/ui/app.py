"""Точка входа приложения: setup → login → главное окно."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from data.backup_io import DatabaseCorruptionError, prepare_database_startup
from data.paths import default_db_path, ensure_user_data_dirs
from services.bootstrap import BootstrapService
from services.upgrade import UpgradeError, UpgradeService
from ui.auth_dialogs import LoginDialog, SetupDialog
from ui.logging_config import configure_logging, install_excepthook
from ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def run(db_path: Path | None = None) -> int:
    """Создать QApplication, пройти auth-flow и показать главное окно."""
    install_excepthook()
    configure_logging()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Журнал доступности персонала")
    app.setOrganizationName("HR")

    path = db_path or default_db_path()
    ensure_user_data_dirs(path.parent)

    try:
        prepare_database_startup(path)
    except DatabaseCorruptionError as exc:
        logger.error("database corruption at startup: %s", exc)
        QMessageBox.critical(
            None,
            "Повреждение базы данных",
            str(exc),
        )
        return 1

    conn = None
    session = None
    if BootstrapService().needs_setup(path):
        setup = SetupDialog(path)
        if setup.exec() != QDialog.DialogCode.Accepted:
            return 1
        conn, session = setup.conn, setup.session
    else:
        login = LoginDialog(path)
        if login.exec() != QDialog.DialogCode.Accepted:
            return 1
        conn, session = login.conn, login.session

    assert conn is not None and session is not None
    try:
        UpgradeService(conn, session, db_path=path).apply_pending()
    except UpgradeError as exc:
        logger.error("schema upgrade failed: %s", exc)
        QMessageBox.critical(
            None,
            "Обновление базы данных",
            "Не удалось применить обновление схемы базы данных.\n\n"
            "Данные восстановлены из автоматической резервной копии, "
            "сделанной перед обновлением. Обратитесь к администратору.",
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
