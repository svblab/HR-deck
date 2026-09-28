"""Точка входа приложения: setup → login → главное окно."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from data.backup_io import DatabaseCorruptionError, prepare_database_startup
from data.paths import default_db_path, ensure_user_data_dirs
from services.bootstrap import BootstrapService
from services.upgrade import UpgradeError, UpgradeService
from ui.app_icon import install_app_window_icon
from ui.auth_dialogs import SetupDialog
from ui.logging_config import configure_logging, install_excepthook
from ui.main_window import MainWindow
from ui.session_activity import install_session_activity_filter
from ui.splash_login_dialog import SplashLoginDialog

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="personnel-availability",
        description="Журнал доступности персонала",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "Режим демо для презентации: временная БД с синтетическими данными, "
            "авто-вход (login=demo / password=demo). Не затрагивает рабочую БД. "
            "Также: env PERSONNEL_AVAILABILITY_DEMO=1."
        ),
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Путь к файлу БД (только для тестов; в --demo игнорируется)",
    )
    return parser.parse_args(argv)


def _demo_requested(cli_demo: bool) -> bool:
    if cli_demo:
        return True
    env = os.environ.get("PERSONNEL_AVAILABILITY_DEMO", "").strip().lower()
    return env in ("1", "true", "yes", "on")


def run(db_path: Path | None = None, *, demo: bool = False) -> int:
    """Создать QApplication, пройти auth-flow и показать главное окно."""
    install_excepthook()
    configure_logging()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Журнал доступности персонала")
    app.setOrganizationName("HR")
    if isinstance(app, QApplication):
        install_app_window_icon(app)

    is_demo = demo
    if is_demo:
        from services.demo import demo_data_dir, demo_db_path, prepare_demo_database

        # Изоляция: в demo всегда свой каталог, --db не подменяет путь на рабочую БД
        if db_path is not None:
            logger.warning("--db ignored in --demo mode; using demo data dir")
        path = demo_db_path()
        ensure_user_data_dirs(path.parent)
        try:
            prepare_database_startup(path)
        except DatabaseCorruptionError as exc:
            logger.error("demo database corruption: %s", exc)
            QMessageBox.critical(None, "Повреждение базы данных (демо)", str(exc))
            return 1
        try:
            conn, session = prepare_demo_database(path, force_reset=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("demo prepare failed")
            QMessageBox.critical(
                None,
                "Режим демо",
                f"Не удалось подготовить демо-базу:\n{exc}",
            )
            return 1
        logger.info("demo mode: data dir=%s", demo_data_dir())
    else:
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
            login = SplashLoginDialog(path)
            login.prepare_startup_presentation()
            if login.exec() != QDialog.DialogCode.Accepted:
                return 1
            conn, session = login.conn, login.session

    assert conn is not None and session is not None
    if isinstance(app, QApplication):
        install_session_activity_filter(app, session)
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

    window = MainWindow(
        conn=conn,
        session=session,
        db_path=path,
        is_demo=is_demo,
    )
    window.showFullScreen()
    return app.exec()


def main() -> None:
    args = _parse_args()
    demo = _demo_requested(args.demo)
    raise SystemExit(run(db_path=args.db, demo=demo))


if __name__ == "__main__":
    main()
