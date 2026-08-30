"""Integration: безопасное обновление с pre-upgrade бэкапом (EPIC-015)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from data.db import connect, create_database, generate_master_key
from data.keywrap import KeywrapFile, keywrap_path_for, save_keywrap, wrap_secret
from data.migrations import (
    apply_pending_migrations,
    current_version,
    default_migrations_dir,
)
from data.paths import default_backups_dir
from domain.permissions import RoleCode
from services.session import SessionState
from services.upgrade import UpgradeError, UpgradeService
from tests.fixtures.synthetic import seed_synthetic_org


def _save_keywrap(db_path: Path, key: bytes) -> None:
    save_keywrap(
        keywrap_path_for(db_path),
        KeywrapFile(wraps=[wrap_secret(key, "test-pass", kind="account", login="admin")]),
    )


def _copy_migrations(dst: Path, *, up_to: int) -> None:
    src = default_migrations_dir()
    for path in sorted(src.glob("*.sql")):
        version = int(path.name[:4])
        if version <= up_to:
            shutil.copy(path, dst / path.name)


def _session(key: bytes, account_id: int = 1) -> SessionState:
    return SessionState(
        account_id=account_id,
        login="admin",
        role=RoleCode.ADMINISTRATOR,
        master_key=key,
    )


def _employee_rows(conn) -> list[tuple]:
    return conn.execute(
        "SELECT id, full_name FROM employees ORDER BY id"
    ).fetchall()


@pytest.mark.acceptance
def test_upgrade_applies_pending_and_creates_pre_upgrade_backup(tmp_path: Path) -> None:
    key = generate_master_key()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "personnel.db"

    old_migs = tmp_path / "migs_v1"
    old_migs.mkdir()
    _copy_migrations(old_migs, up_to=1)

    conn = create_database(db_path, key)
    apply_pending_migrations(conn, old_migs)
    seed_synthetic_org(conn)
    before = _employee_rows(conn)
    conn.close()
    _save_keywrap(db_path, key)

    new_migs = tmp_path / "migs_all"
    new_migs.mkdir()
    _copy_migrations(new_migs, up_to=8)

    conn = connect(db_path, key)
    session = _session(key)
    svc = UpgradeService(
        conn, session, db_path=db_path, clock=lambda: "2026-08-30T21:00:00Z"
    )
    applied = svc.apply_pending(migrations_dir=new_migs)
    assert applied
    assert current_version(conn) == 8
    assert _employee_rows(conn) == before
    backups = list(default_backups_dir(data_dir).glob("pre-upgrade-*.db"))
    assert backups
    conn.close()


@pytest.mark.acceptance
def test_upgrade_rollback_restores_pre_upgrade_state(tmp_path: Path) -> None:
    key = generate_master_key()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "personnel.db"

    mig_v1 = tmp_path / "migs_v1"
    mig_v1.mkdir()
    _copy_migrations(mig_v1, up_to=1)

    conn = create_database(db_path, key)
    apply_pending_migrations(conn, mig_v1)
    seed_synthetic_org(conn)
    before = _employee_rows(conn)
    history_before = conn.execute(
        "SELECT id, status_id, start_date, end_date FROM status_history ORDER BY id"
    ).fetchall()
    conn.close()
    _save_keywrap(db_path, key)

    mig_bad = tmp_path / "migs_bad"
    mig_bad.mkdir()
    _copy_migrations(mig_bad, up_to=1)
    (mig_bad / "0002_bad.sql").write_text(
        "CREATE TABLE upgrade_should_not_remain(id INTEGER PRIMARY KEY);\n"
        "INSERT INTO missing_table VALUES (1);\n",
        encoding="utf-8",
    )

    conn = connect(db_path, key)
    session = _session(key)
    svc = UpgradeService(
        conn, session, db_path=db_path, clock=lambda: "2026-08-30T21:10:00Z"
    )
    with pytest.raises(UpgradeError, match="restored from pre-upgrade"):
        svc.apply_pending(migrations_dir=mig_bad)

    conn2 = connect(db_path, key)
    assert current_version(conn2) == 1
    assert _employee_rows(conn2) == before
    assert (
        conn2.execute(
            "SELECT id, status_id, start_date, end_date FROM status_history ORDER BY id"
        ).fetchall()
        == history_before
    )
    assert not conn2.execute(
        "SELECT name FROM sqlite_master WHERE name='upgrade_should_not_remain'"
    ).fetchone()
    events = conn2.execute(
        "SELECT event_type, message FROM technical_events "
        "WHERE event_type LIKE 'upgrade.%'"
    ).fetchall()
    assert any("rollback success" in msg for _t, msg in events)
    conn2.close()


@pytest.mark.acceptance
def test_upgrade_noop_when_schema_current(tmp_path: Path) -> None:
    key = generate_master_key()
    db_path = tmp_path / "personnel.db"
    conn = create_database(db_path, key)
    apply_pending_migrations(conn)
    session = _session(key)
    svc = UpgradeService(
        conn, session, db_path=db_path, clock=lambda: "2026-08-30T21:20:00Z"
    )
    assert svc.apply_pending() == []
    assert not list(default_backups_dir(tmp_path).glob("pre-upgrade-*.db"))
    conn.close()
