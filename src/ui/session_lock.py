"""Закрытие открытых модальных окон перед блокировкой сессии."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog, QWidget


def _collect_visible_dialogs(
    main_window: QWidget | None,
    *,
    exclude: type[QDialog] | tuple[type[QDialog], ...] = (),
) -> list[QDialog]:
    exclude_types = exclude if isinstance(exclude, tuple) else (exclude,)
    found: list[QDialog] = []
    seen: set[int] = set()

    def add(dialog: QDialog) -> None:
        dialog_id = id(dialog)
        if dialog_id in seen or not dialog.isVisible():
            return
        if exclude_types and isinstance(dialog, exclude_types):
            return
        seen.add(dialog_id)
        found.append(dialog)

    app = QApplication.instance()
    if isinstance(app, QApplication):
        for widget in app.topLevelWidgets():
            if isinstance(widget, QDialog):
                add(widget)
            for child in widget.findChildren(QDialog):
                add(child)

    if main_window is not None:
        for child in main_window.findChildren(QDialog):
            add(child)

    return found


def dismiss_open_modal_dialogs(
    main_window: QWidget | None = None,
    *,
    exclude: type[QDialog] | tuple[type[QDialog], ...] = (),
) -> None:
    """Отклонить все видимые QDialog, кроме указанных типов (например UnlockDialog)."""
    for dialog in _collect_visible_dialogs(main_window, exclude=exclude):
        if dialog.isVisible():
            dialog.reject()
