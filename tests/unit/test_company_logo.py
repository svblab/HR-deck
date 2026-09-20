"""Масштабирование логотипа компании в badge заголовка."""

from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from ui.company_logo import logo_badge_content_size, scale_company_logo_pixmap


def test_logo_badge_content_size_matches_theme_padding() -> None:
    assert logo_badge_content_size() == (32, 22)


def test_scale_company_logo_pixmap_preserves_wide_aspect_ratio(qapp: QApplication) -> None:
    source = QPixmap(200, 100)
    max_w, max_h = logo_badge_content_size()
    scaled = scale_company_logo_pixmap(source, max_width=max_w, max_height=max_h)

    assert not scaled.isNull()
    assert scaled.width() <= max_w
    assert scaled.height() <= max_h
    assert abs(scaled.width() / scaled.height() - 2.0) < 0.01


def test_scale_company_logo_pixmap_preserves_tall_aspect_ratio(qapp: QApplication) -> None:
    source = QPixmap(100, 200)
    max_w, max_h = logo_badge_content_size()
    scaled = scale_company_logo_pixmap(source, max_width=max_w, max_height=max_h)

    assert not scaled.isNull()
    assert scaled.width() <= max_w
    assert scaled.height() <= max_h
    assert abs(scaled.width() / scaled.height() - 0.5) < 0.01
