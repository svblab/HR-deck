"""UI: журнал действий только для чтения, без кнопок изменения (ТЗ §4.6)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QAbstractItemView, QPushButton, QTableWidget

from services.bootstrap import BootstrapService
from services.user_action_log import UserActionLogService
from ui.action_log_dialog import ActionLogDialog


def test_dialog_is_read_only_and_lists_bootstrap_entry(qtbot, tmp_path: Path) -> None:
    conn, session, _code = BootstrapService(
        clock=lambda: "2026-08-26T12:00:00Z"
    ).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    dialog = ActionLogDialog(UserActionLogService(conn, session))
    qtbot.addWidget(dialog)
    table = dialog.findChild(QTableWidget, "actionLogTable")
    assert table is not None
    assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert table.rowCount() >= 1
    assert not dialog.has_mutating_controls()
    labels = [b.text().casefold() for b in dialog.findChildren(QPushButton)]
    assert "excel" in labels
    assert all("удал" not in t and "измен" not in t and "редакт" not in t for t in labels)
    dialog.close()
    conn.close()
