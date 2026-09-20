"""Встроенные изображения заставки (Qt resource system)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

import ui.ui_resources_rc  # noqa: F401 — регистрация ресурсов

SPLASH_IMAGE_RESOURCE = ":/ui/Splash/splash.png"


def load_splash_pixmap() -> QPixmap:
    """Загрузить splash.png из Qt resources; пустой QPixmap при отсутствии."""
    pixmap = QPixmap(SPLASH_IMAGE_RESOURCE)
    return pixmap


def scale_splash_pixmap(pixmap: QPixmap, max_width: int, max_height: int) -> QPixmap:
    """Вписать splash в прямоугольник без искажения пропорций."""
    if pixmap.isNull() or max_width <= 0 or max_height <= 0:
        return QPixmap()
    return pixmap.scaled(
        max_width,
        max_height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
