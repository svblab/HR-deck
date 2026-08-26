"""Часы главного окна — формат как в HTML-прототипе (EPIC-001 / ТЗ §3.4 оболочка)."""

from datetime import datetime

import pytest

from ui.main_window import format_clock


@pytest.mark.acceptance
def test_format_clock_matches_prototype_layout() -> None:
    """ТЗ §11 / прототип: время HH:MM:SS и дата с днём недели на русском."""
    now = datetime(2026, 8, 26, 21, 5, 7)  # среда
    time_text, date_text = format_clock(now)
    assert time_text == "21:05:07"
    assert date_text == "среда, 26 августа 2026"
