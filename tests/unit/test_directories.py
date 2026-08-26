"""Unit: валидация имён справочников."""

from __future__ import annotations

import pytest

from services.directories import DirectoryError, _clean_code, _clean_name


def test_clean_name_rejects_blank() -> None:
    with pytest.raises(DirectoryError):
        _clean_name("  ")


def test_clean_name_strips() -> None:
    assert _clean_name("  Alpha  ") == "Alpha"


def test_clean_code_normalizes() -> None:
    assert _clean_code("  STAFF  ") == "staff"


def test_clean_code_rejects_blank() -> None:
    with pytest.raises(DirectoryError):
        _clean_code("")
