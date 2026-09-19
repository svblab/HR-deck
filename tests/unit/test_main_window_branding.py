"""UI: брендинг в заголовке главного окна после входа."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel

from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from ui.main_window import MainWindow


def _admin_window(tmp_path: Path) -> tuple[MainWindow, object, AccountManagementService]:
    db = tmp_path / "app.db"
    clock = lambda: "2026-09-13T14:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    service = AccountManagementService(conn, session, db_path=db, clock=clock)
    window = MainWindow(conn=conn, session=session, db_path=db)
    return window, conn, service


def test_refresh_branding_updates_company_name(qtbot, tmp_path: Path) -> None:
    window, conn, service = _admin_window(tmp_path)
    qtbot.addWidget(window)

    service.update_company_profile(company_name="ООО Альфа")
    window._refresh_branding()

    company = window.findChild(QLabel, "brandCompany")
    assert company is not None
    assert company.text() == "ООО Альфа"

    window.close()
    conn.close()  # type: ignore[union-attr]


def test_refresh_branding_invalid_logo_falls_back_to_placeholder(qtbot, tmp_path: Path) -> None:
    window, conn, service = _admin_window(tmp_path)
    qtbot.addWidget(window)

    service.update_company_profile(logo_path=str(tmp_path / "missing-logo.png"))
    window._refresh_branding()

    logo = window.findChild(QLabel, "logoBadge")
    assert logo is not None
    assert logo.text() == "ЛОГО"
    assert logo.pixmap() is None or logo.pixmap().isNull()

    window.close()
    conn.close()  # type: ignore[union-attr]


def test_refresh_branding_loads_valid_logo(qtbot, tmp_path: Path) -> None:
    window, conn, service = _admin_window(tmp_path)
    qtbot.addWidget(window)

    logo_path = tmp_path / "logo.png"
    pixmap = QPixmap(32, 32)
    pixmap.fill()
    assert pixmap.save(str(logo_path))

    service.update_company_profile(logo_path=str(logo_path))
    window._refresh_branding()

    logo = window.findChild(QLabel, "logoBadge")
    assert logo is not None
    assert logo.text() == ""
    assert logo.pixmap() is not None
    assert not logo.pixmap().isNull()

    window.close()
    conn.close()  # type: ignore[union-attr]
