"""Масштабирование логотипа компании в badge заголовка."""

from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from ui.company_logo import (
    LOGO_BADGE_OUTER_HEIGHT,
    TITLE_BAR_HEIGHT,
    logo_badge_content_size,
    scale_company_logo_pixmap,
)


def test_logo_badge_content_size_matches_theme_padding() -> None:
    assert logo_badge_content_size() == (35, 24)


def test_logo_badge_fits_title_bar() -> None:
    assert LOGO_BADGE_OUTER_HEIGHT < TITLE_BAR_HEIGHT


def test_scale_company_logo_pixmap_fills_wide_logo_frame(qapp: QApplication) -> None:
    source = QPixmap(200, 100)
    max_w, max_h = logo_badge_content_size()
    scaled = scale_company_logo_pixmap(source, max_width=max_w, max_height=max_h)

    assert not scaled.isNull()
    assert scaled.width() == max_w
    assert scaled.height() == max_h


def test_scale_company_logo_pixmap_fills_tall_logo_frame(qapp: QApplication) -> None:
    source = QPixmap(100, 200)
    max_w, max_h = logo_badge_content_size()
    scaled = scale_company_logo_pixmap(source, max_width=max_w, max_height=max_h)

    assert not scaled.isNull()
    assert scaled.width() == max_w
    assert scaled.height() == max_h
