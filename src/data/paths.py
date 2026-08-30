"""Пути каталога данных приложения (отдельно от установки — ТЗ §8)."""

from __future__ import annotations

import os
from pathlib import Path


def default_data_dir() -> Path:
    """
    Каталог данных: $PERSONNEL_AVAILABILITY_DATA или ~/.local/share/personnel-availability.
    """
    override = os.environ.get("PERSONNEL_AVAILABILITY_DATA")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "personnel-availability"


def default_db_path(data_dir: Path | None = None) -> Path:
    root = data_dir or default_data_dir()
    return root / "personnel.db"


def templates_storage_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "templates"
