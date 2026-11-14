"""E1-08: EmploymentTypeRecord owner/sort fields and owner+code lookup."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import create_database, generate_master_key
from data.directories import EmploymentTypeRecord, EmploymentTypeRepository
from data.migrations import apply_pending_migrations, default_migrations_dir

_OWNER_SCHEMA_SUFFIX = "_employment_type_owner_schema.sql"
_NOW = "2026-08-01T10:00:00Z"


def _owner_schema_migration() -> Path:
    matches = sorted(
        p for p in default_migrations_dir().glob("*.sql") if p.name.endswith(_OWNER_SCHEMA_SUFFIX)
    )
    assert len(matches) == 1, f"expected one {_OWNER_SCHEMA_SUFFIX}, found {matches}"
    return matches[0]


def _copy_migrations(names: list[str], root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    src = default_migrations_dir()
    for name in names:
        shutil.copy(src / name, target / name)
    return target


def _full_migrations_dir(tmp_path: Path) -> Path:
    _owner_schema_migration()  # assert the E1-08 file exists
    all_names = [p.name for p in sorted(default_migrations_dir().glob("*.sql"))]
    return _copy_migrations(all_names, tmp_path / "full")


@pytest.fixture()
def repo_pair(tmp_path: Path) -> Iterator[tuple[sqlcipher.Connection, EmploymentTypeRepository]]:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_full = _full_migrations_dir(tmp_path / "migs")
    conn = create_database(path, key)
    apply_pending_migrations(conn, migrations_dir=mig_full)
    yield conn, EmploymentTypeRepository(conn)
    conn.close()


def test_record_exposes_owner_branch_id_and_sort_order_defaults(
    repo_pair: tuple[sqlcipher.Connection, EmploymentTypeRepository],
) -> None:
    _conn, repo = repo_pair
    staff = repo.get_by_code("staff")
    assert staff is not None
    assert isinstance(staff, EmploymentTypeRecord)
    assert staff.owner_branch_id is None
    assert staff.sort_order == 0


def test_get_by_owner_and_code_matches_system_null_owner(
    repo_pair: tuple[sqlcipher.Connection, EmploymentTypeRepository],
) -> None:
    _conn, repo = repo_pair
    found = repo.get_by_owner_and_code(None, "staff")
    assert found is not None
    assert found.code == "staff"
    assert found.owner_branch_id is None
    assert repo.get_by_owner_and_code(None, "no-such-code") is None


def test_get_by_owner_and_code_matches_branch_owner(
    repo_pair: tuple[sqlcipher.Connection, EmploymentTypeRepository],
) -> None:
    conn, repo = repo_pair
    conn.execute(
        "INSERT INTO branches (external_id, name, is_archived, created_at, updated_at)"
        " VALUES ('br-e1-08', 'Branch E1-08', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.commit()
    branch_id = int(
        conn.execute("SELECT id FROM branches WHERE external_id = 'br-e1-08'").fetchone()[0]
    )

    conn.execute(
        "INSERT INTO employment_types"
        " (code, name, archives_record, is_archived, created_at, updated_at,"
        "  owner_branch_id, sort_order)"
        " VALUES ('extra', 'Extra', 0, 0, ?, ?, ?, 5)",
        (_NOW, _NOW, branch_id),
    )
    conn.commit()

    owned = repo.get_by_owner_and_code(branch_id, "extra")
    assert owned is not None
    assert owned.code == "extra"
    assert owned.owner_branch_id == branch_id
    assert owned.sort_order == 5
    assert repo.get_by_owner_and_code(None, "extra") is None
    assert repo.get_by_owner_and_code(branch_id + 999, "extra") is None


def test_get_by_code_unchanged_for_system_row(
    repo_pair: tuple[sqlcipher.Connection, EmploymentTypeRepository],
) -> None:
    _conn, repo = repo_pair
    by_code = repo.get_by_code("staff")
    by_owner = repo.get_by_owner_and_code(None, "staff")
    assert by_code is not None and by_owner is not None
    assert by_code.id == by_owner.id
    assert by_code.code == "staff"
