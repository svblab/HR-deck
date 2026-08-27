"""Цвета и общие стили — соответствуют prototype/prototype_glavny_ekran.html."""

from __future__ import annotations

NAVY = "#1B2A3D"
NAVY_2 = "#25384F"
ACCENT = "#2E6E62"
BG = "#F3F4F1"
CARD = "#FFFFFF"
BORDER = "#E1E1DC"
TEXT = "#20241F"
TEXT_MUTED = "#6B6F68"
TITLEBAR_MUTED = "#B9C4D0"

APP_STYLESHEET = f"""
QMainWindow, QWidget#centralRoot {{
    background: {BG};
    color: {TEXT};
}}
QWidget#titleBar {{
    background: {NAVY};
    color: #ffffff;
    min-height: 56px;
    max-height: 56px;
}}
QLabel#logoBadge {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3A5A78, stop:1 #233A50);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.13);
    border-radius: 7px;
    font-weight: 700;
    font-size: 13px;
    padding: 6px 8px;
    min-width: 34px;
    max-width: 48px;
    min-height: 34px;
}}
QLabel#brandCompany {{
    color: #ffffff;
    font-size: 13px;
    font-weight: 600;
}}
QLabel#brandApp {{
    color: {TITLEBAR_MUTED};
    font-size: 11px;
}}
QLineEdit#searchInput {{
    background: rgba(255, 255, 255, 0.08);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 8px;
    padding: 0 12px;
    min-height: 34px;
    max-height: 34px;
    font-size: 13px;
    max-width: 340px;
}}
QLabel#clockTime {{
    color: #ffffff;
    font-size: 16px;
    font-weight: 600;
}}
QLabel#clockDate {{
    color: {TITLEBAR_MUTED};
    font-size: 11px;
}}
QToolButton#titleIconBtn {{
    background: rgba(255, 255, 255, 0.06);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 8px;
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
}}
QToolButton#titleIconBtn:hover {{
    background: rgba(255, 255, 255, 0.13);
}}
QWidget#toolbar {{
    background: {CARD};
    border-bottom: 1px solid {BORDER};
}}
QPushButton {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 0 14px;
    min-height: 34px;
    font-size: 13px;
}}
QPushButton:hover {{
    background: #F4F4F1;
}}
QPushButton#primaryBtn, QPushButton#addEmployeeBtn {{
    background: {ACCENT};
    color: #ffffff;
    border-color: {ACCENT};
}}
QPushButton#primaryBtn:hover, QPushButton#addEmployeeBtn:hover {{
    background: #265A50;
}}
QPushButton#viewToggleActive {{
    background: {NAVY};
    color: #ffffff;
    border-radius: 0;
}}
QPushButton#viewToggleInactive {{
    background: {CARD};
    color: {TEXT_MUTED};
    border-radius: 0;
}}
QComboBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    min-height: 34px;
    padding: 0 10px;
    font-size: 13px;
}}
QPushButton#filterReset {{
    background: transparent;
    border: none;
    color: {TEXT_MUTED};
    text-decoration: underline;
    min-height: 24px;
    padding: 0 2px;
    font-size: 12px;
}}
QLabel#contentPlaceholder {{
    color: {TEXT_MUTED};
    font-size: 14px;
}}
QFrame#boardColumn {{
    background: #EFEFEA;
    border-radius: 12px;
}}
QFrame#empCard {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#countBadge {{
    font-size: 11px;
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 20px;
    padding: 1px 8px;
    color: {TEXT_MUTED};
}}
QPushButton#clarificationCounter {{
    background: #FBEAEA;
    color: #A32D2D;
    border: 1px solid #F0B8B8;
}}
QLabel#summaryStrip {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}
"""
