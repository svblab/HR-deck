"""Integration: разделение каталогов данных (EPIC-015, ТЗ §8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.paths import (
    default_backups_dir,
    default_data_dir,
    default_db_path,
    templates_storage_dir,
)
from services.backup import BackupService
from services.bootstrap import BootstrapService
from services.template_library import TemplateLibraryService
from tests.fixtures.synthetic import seed_synthetic_org


@pytest.mark.acceptance
def test_data_dir_override_unifies_paths(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "custom-data"
    monkeypatch.setenv("PERSONNEL_AVAILABILITY_DATA", str(root))
    assert default_data_dir() == root
    assert default_db_path() == root / "personnel.db"
    assert default_backups_dir() == root / "backups"
    assert templates_storage_dir() == root / "templates"


@pytest.mark.acceptance
def test_backup_defaults_to_data_backups_dir(monkeypatch, tmp_path: Path) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("PERSONNEL_AVAILABILITY_DATA", str(data))
    db = default_db_path()
    bootstrap = BootstrapService(clock=lambda: "2026-08-30T20:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    seed_synthetic_org(conn)
    backup = BackupService(conn, session, db_path=db, clock=lambda: "2026-08-30T20:01:00Z")
    path = backup.create_backup(default_backups_dir())
    assert path.parent == data / "backups"
    assert path.is_file()
    conn.close()


@pytest.mark.acceptance
def test_template_library_uses_templates_under_data_dir(
    monkeypatch, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("PERSONNEL_AVAILABILITY_DATA", str(data))
    db = default_db_path()
    bootstrap = BootstrapService(clock=lambda: "2026-08-30T20:10:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    svc = TemplateLibraryService(conn, session, data_dir=data)
    assert svc._storage_root == data / "templates"
    conn.close()
