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


def cover_splash_pixmap(pixmap: QPixmap, target_width: int, target_height: int) -> QPixmap:
    """
    Масштабировать splash в стиле cover: заполнить прямоугольник без искажения,
    при необходимости обрезать края по центру.
    """
    if pixmap.isNull() or target_width <= 0 or target_height <= 0:
        return QPixmap()
    src_w = pixmap.width()
    src_h = pixmap.height()
    if src_w <= 0 or src_h <= 0:
        return QPixmap()

    scale = max(target_width / src_w, target_height / src_h)
    scaled_w = max(1, int(src_w * scale + 0.5))
    scaled_h = max(1, int(src_h * scale + 0.5))
    scaled = pixmap.scaled(
        scaled_w,
        scaled_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - target_width) // 2)
    y = max(0, (scaled.height() - target_height) // 2)
    crop_w = min(target_width, scaled.width() - x)
    crop_h = min(target_height, scaled.height() - y)
    return scaled.copy(x, y, crop_w, crop_h)
