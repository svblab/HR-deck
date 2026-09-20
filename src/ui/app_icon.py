"""Фиксированная иконка приложения для системного декора окна (не логотип компании)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QWidget

_ICON_PATH = Path(__file__).resolve().parent / "resources" / "app_icon.png"
_cached_icon: QIcon | None = None


def app_icon_path() -> Path:
    """Путь к встроенному PNG-файлу иконки приложения."""
    return _ICON_PATH


def load_app_icon() -> QIcon:
    """Загрузить QIcon один раз и вернуть кэшированный экземпляр."""
    global _cached_icon
    if _cached_icon is None:
        path = app_icon_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"Application icon not found: {path}. "
                "Place app_icon.png in src/ui/resources/."
            )
        _cached_icon = QIcon(str(path))
    return _cached_icon


def apply_app_window_icon(widget: QWidget) -> None:
    """Установить иконку приложения на конкретное окно (диалог, главное окно)."""
    widget.setWindowIcon(load_app_icon())


class _AppWindowIconFilter(QObject):
    """Дублирует иконку приложения на top-level окна (Linux не всегда наследует от QApplication)."""

    def __init__(self, icon: QIcon) -> None:
        super().__init__()
        self._icon = icon

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget):
            if watched.isWindow() and watched.windowIcon().isNull():
                watched.setWindowIcon(self._icon)
        return super().eventFilter(watched, event)


def install_app_window_icon(app: QApplication) -> QIcon:
    """Установить иконку на QApplication и подписать фильтр для дочерних окон."""
    icon = load_app_icon()
    app.setWindowIcon(icon)

    existing = getattr(app, "_app_window_icon_filter", None)
    if isinstance(existing, _AppWindowIconFilter):
        return icon
    if existing is not None:
        app.removeEventFilter(existing)

    filter_ = _AppWindowIconFilter(icon)
    app.installEventFilter(filter_)
    app._app_window_icon_filter = filter_  # type: ignore[attr-defined]
    return icon
