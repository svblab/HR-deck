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


def logs_dir(data_dir: Path | None = None) -> Path:
    """Каталог файловых логов приложения (ТЗ §8)."""
    return (data_dir or default_data_dir()) / "logs"


def ensure_user_data_dirs(data_dir: Path | None = None) -> Path:
    """Создать каталоги данных, бэкапов, логов и шаблонов при первом запуске."""
    root = data_dir or default_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("backups", "logs", "templates"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root
