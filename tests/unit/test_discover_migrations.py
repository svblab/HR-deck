"""Unit: непрерывная последовательность версий миграций (P0-1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import DatabaseError
from data.migrations import discover_migrations, expected_migration_versions


def _write(dir_path: Path, name: str, body: str = "SELECT 1;\n") -> None:
    (dir_path / name).write_text(body, encoding="utf-8")


def test_discover_ok_single_and_sequence(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a.sql")
    assert expected_migration_versions(tmp_path) == [1]

    _write(tmp_path, "0002_b.sql")
    _write(tmp_path, "0003_c.sql")
    assert expected_migration_versions(tmp_path) == [1, 2, 3]
    assert [m.version for m in discover_migrations(tmp_path)] == [1, 2, 3]


def test_discover_rejects_gap(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a.sql")
    _write(tmp_path, "0003_c.sql")
    with pytest.raises(DatabaseError, match="missing migration"):
        discover_migrations(tmp_path)


def test_discover_rejects_start_not_one(tmp_path: Path) -> None:
    _write(tmp_path, "0002_only.sql")
    with pytest.raises(DatabaseError, match="must start at 0001"):
        discover_migrations(tmp_path)


def test_discover_rejects_duplicate(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a.sql")
    _write(tmp_path, "0001_b.sql")
    with pytest.raises(DatabaseError, match="duplicate"):
        discover_migrations(tmp_path)
