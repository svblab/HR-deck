"""Масштабирование логотипа компании для badge в заголовке главного окна."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

TITLE_BAR_HEIGHT = 56
TITLE_BAR_LOGO_VERTICAL_MARGIN = 8

# Соответствует QLabel#logoBadge в theme.py.
_LOGO_BADGE_BASE_CONTENT_WIDTH = 32
_LOGO_BADGE_BASE_CONTENT_HEIGHT = 22
_LOGO_BADGE_BASE_PADDING_H = 8
_LOGO_BADGE_BASE_PADDING_V = 6
LOGO_BADGE_SCALE = 1.1

LOGO_BADGE_PADDING_H = round(_LOGO_BADGE_BASE_PADDING_H * LOGO_BADGE_SCALE)
LOGO_BADGE_PADDING_V = round(_LOGO_BADGE_BASE_PADDING_V * LOGO_BADGE_SCALE)
LOGO_BADGE_CONTENT_WIDTH = max(1, round(_LOGO_BADGE_BASE_CONTENT_WIDTH * LOGO_BADGE_SCALE))
LOGO_BADGE_CONTENT_HEIGHT = max(1, round(_LOGO_BADGE_BASE_CONTENT_HEIGHT * LOGO_BADGE_SCALE))
LOGO_BADGE_MAX_OUTER_HEIGHT = TITLE_BAR_HEIGHT - TITLE_BAR_LOGO_VERTICAL_MARGIN

LOGO_BADGE_OUTER_WIDTH = LOGO_BADGE_CONTENT_WIDTH + 2 * LOGO_BADGE_PADDING_H
LOGO_BADGE_OUTER_HEIGHT = min(
    LOGO_BADGE_CONTENT_HEIGHT + 2 * LOGO_BADGE_PADDING_V,
    LOGO_BADGE_MAX_OUTER_HEIGHT,
)


def logo_badge_content_size() -> tuple[int, int]:
    """Внутренний размер области под pixmap с учётом padding badge."""
    return (LOGO_BADGE_CONTENT_WIDTH, LOGO_BADGE_CONTENT_HEIGHT)


def scale_company_logo_pixmap(
    pixmap: QPixmap,
    *,
    max_width: int,
    max_height: int,
    device_pixel_ratio: float = 1.0,
) -> QPixmap:
    """Заполнить прямоугольник max_width×max_height без искажения (cover + crop)."""
    if pixmap.isNull() or max_width <= 0 or max_height <= 0:
        return QPixmap()

    dpr = device_pixel_ratio if device_pixel_ratio > 0 else 1.0
    target_w = max(1, int(max_width * dpr))
    target_h = max(1, int(max_height * dpr))
    expanded = pixmap.scaled(
        target_w,
        target_h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    crop_x = max(0, (expanded.width() - target_w) // 2)
    crop_y = max(0, (expanded.height() - target_h) // 2)
    cropped = expanded.copy(crop_x, crop_y, target_w, target_h)
    if dpr != 1.0:
        cropped.setDevicePixelRatio(dpr)
    return cropped
