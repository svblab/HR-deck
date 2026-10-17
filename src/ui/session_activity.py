"""Сброс таймера бездействия по вводу пользователя во всём приложении."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from services.session import SessionState

_ACTIVITY_EVENTS = frozenset(
    {
        QEvent.Type.MouseButtonPress,
        QEvent.Type.KeyPress,
        QEvent.Type.Wheel,
        QEvent.Type.TouchBegin,
        QEvent.Type.TabletPress,
    }
)


class SessionActivityFilter(QObject):
    """Сбрасывает idle-таймер сессии при активности пользователя в любом окне."""

    def __init__(self, session: SessionState) -> None:
        super().__init__()
        self._session = session

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            event.type() in _ACTIVITY_EVENTS
            and not self._session.locked
        ):
            self._session.touch()
        return super().eventFilter(watched, event)


def install_session_activity_filter(
    app: QApplication,
    session: SessionState,
) -> SessionActivityFilter:
    """Установить глобальный фильтр активности; вернуть его для снятия при необходимости."""
    existing = getattr(app, "_session_activity_filter", None)
    if isinstance(existing, SessionActivityFilter):
        if existing._session is session:
            return existing
        app.removeEventFilter(existing)

    filter_ = SessionActivityFilter(session)
    app.installEventFilter(filter_)
    app._session_activity_filter = filter_  # type: ignore[attr-defined]
    return filter_
