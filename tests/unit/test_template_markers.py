"""Unit: каталог и синтаксис маркеров {{…}} (ADR-0005 / ТЗ §11 шаблоны)."""

from __future__ import annotations

from domain.template_markers import (
    extract_markers,
    find_malformed_marker_fragments,
)


def test_extract_markers_ignores_incomplete_closing_brace() -> None:
    """Регрессия #36: MARKER_RE не видит {{должность} как токен."""
    assert extract_markers("{{должность}") == []
    assert extract_markers("x {{заголовок}} y {{должность}") == ["заголовок"]


def test_find_malformed_detects_single_closing_brace() -> None:
    """ТЗ §11 / ADR-0005: битый синтаксис {{…} должен обнаруживаться явно."""
    found = find_malformed_marker_fragments("{{должность}")
    assert found
    assert any("должность" in f for f in found)


def test_find_malformed_detects_unclosed_open() -> None:
    found = find_malformed_marker_fragments("prefix {{заголовок")
    assert found


def test_find_malformed_ignores_valid_markers() -> None:
    assert find_malformed_marker_fragments("{{заголовок}} и {{ФИО}}") == []
    assert find_malformed_marker_fragments("{{#ROW}}") == []
    assert find_malformed_marker_fragments("plain text") == []
