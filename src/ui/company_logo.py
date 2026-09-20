"""Масштабирование логотипа компании для badge в заголовке главного окна."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

# Соответствует QLabel#logoBadge в theme.py.
LOGO_BADGE_OUTER_WIDTH = 48
LOGO_BADGE_OUTER_HEIGHT = 34
LOGO_BADGE_PADDING_H = 8
LOGO_BADGE_PADDING_V = 6


def logo_badge_content_size() -> tuple[int, int]:
    """Внутренний размер области под pixmap с учётом padding badge."""
    return (
        max(1, LOGO_BADGE_OUTER_WIDTH - 2 * LOGO_BADGE_PADDING_H),
        max(1, LOGO_BADGE_OUTER_HEIGHT - 2 * LOGO_BADGE_PADDING_V),
    )


def scale_company_logo_pixmap(
    pixmap: QPixmap,
    *,
    max_width: int,
    max_height: int,
    device_pixel_ratio: float = 1.0,
) -> QPixmap:
    """Вписать pixmap в прямоугольник max_width×max_height без искажения пропорций."""
    if pixmap.isNull() or max_width <= 0 or max_height <= 0:
        return QPixmap()

    dpr = device_pixel_ratio if device_pixel_ratio > 0 else 1.0
    target_w = max(1, int(max_width * dpr))
    target_h = max(1, int(max_height * dpr))
    scaled = pixmap.scaled(
        target_w,
        target_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if dpr != 1.0:
        scaled.setDevicePixelRatio(dpr)
    return scaled
