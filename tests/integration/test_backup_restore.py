"""Integration: резервное копирование и восстановление (EPIC-012)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.backup_io import (
    DatabaseCorruptionError,
    atomic_copy_file,
    prepare_database_startup,
    swap_live_from_backup,
)
from data.db import connect
from data.keywrap import keywrap_path_for
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationService
from services.authorization import AuthorizationError
from services.backup import BackupError, BackupService
from services.bootstrap import BootstrapService
from services.session import SessionState
from tests.fixtures.synthetic import seed_synthetic_org


def _open(tmp_path: Path):
    clock = lambda: "2026-08-30T15:00:00Z"  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    backup = BackupService(conn, session, db_path=db, clock=clock)
    return db, conn, session, backup, ids, clock


@pytest.mark.acceptance
def test_create_backup_happy_path_and_verify(tmp_path: Path) -> None:
    db, conn, session, backup, ids, _clock = _open(tmp_path)
    dest = tmp_path / "external"
    path = backup.create_backup(dest)
    assert path.is_file()
    assert keywrap_path_for(path).is_file()
    verify = BackupService(conn, session, db_path=db)
    verify.verify_backup(path)
    conn2 = connect(path, session.master_key)
    name = conn2.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0]
    assert name == "Иванов Иван Иванович"
    conn2.close()
    conn.close()


@pytest.mark.acceptance
def test_create_backup_verify_failure_removes_file(monkeypatch, tmp_path: Path) -> None:
    db, conn, session, backup, _ids, _clock = _open(tmp_path)
    dest = tmp_path / "external"

    def _fail(path, key):  # noqa: ANN001
        raise OSError("simulated verify failure")

    monkeypatch.setattr("services.backup.verify_database_file", _fail)
    with pytest.raises(BackupError):
        backup.create_backup(dest)
    assert list(dest.glob("*.db")) == []
    conn.close()


@pytest.mark.acceptance
def test_restore_round_trip(tmp_path: Path) -> None:
    db, conn, session, backup, ids, clock = _open(tmp_path)
    dest = tmp_path / "external"
    snapshot = backup.create_backup(dest)
    conn.execute(
        "UPDATE employees SET full_name = ? WHERE id = ?",
        ("После бэкапа", ids["employee_a_id"]),
    )
    conn.commit()
    new_conn = backup.restore_backup(snapshot)
    row = new_conn.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()
    assert row[0] == "Иванов Иван Иванович"
    new_conn.close()


@pytest.mark.acceptance
def test_restore_verify_failure_leaves_live_intact(tmp_path: Path) -> None:
    db, conn, session, backup, ids, _clock = _open(tmp_path)
    dest = tmp_path / "external"
    good = backup.create_backup(dest)
    bad = dest / "bad.db"
    atomic_copy_file(good, bad)
    bad.write_bytes(bad.read_bytes()[:128])
    atomic_copy_file(keywrap_path_for(good), keywrap_path_for(bad))
    before = conn.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0]
    with pytest.raises(BackupError):
        backup.restore_backup(bad)
    conn2 = connect(db, session.master_key)
    after = conn2.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0]
    assert after == before
    conn2.close()
    conn.close()


@pytest.mark.acceptance
def test_atomic_swap_leaves_live_consistent_on_partial(monkeypatch, tmp_path: Path) -> None:
    db, conn, session, backup, _ids, _clock = _open(tmp_path)
    dest = tmp_path / "external"
    snapshot = backup.create_backup(dest)
    conn.close()

    def _boom(src, dst):  # noqa: ANN001
        raise OSError("simulated copy failure")

    monkeypatch.setattr("data.backup_io.atomic_copy_file", _boom)
    with pytest.raises(OSError):
        swap_live_from_backup(db, snapshot)
    assert db.is_file()
    conn2 = connect(db, session.master_key)
    conn2.close()


@pytest.mark.acceptance
def test_backup_rbac(tmp_path: Path) -> None:
    db, conn, session, backup, _ids, clock = _open(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=clock
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    hr = SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=session.master_key,
    )
    hr_backup = BackupService(conn, hr, db_path=db, clock=clock)
    hr_path = hr_backup.create_backup(tmp_path / "hr-copy")
    with pytest.raises(AuthorizationError):
        hr_backup.restore_backup(hr_path)
    conn.close()


@pytest.mark.acceptance
def test_observer_cannot_create_backup(tmp_path: Path) -> None:
    db, conn, session, _backup, _ids, clock = _open(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=clock
    )
    obs_id = mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    obs = SessionState(
        account_id=obs_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=session.master_key,
    )
    with pytest.raises(AuthorizationError):
        BackupService(conn, obs, db_path=db).create_backup(tmp_path / "x")
    conn.close()


@pytest.mark.acceptance
def test_startup_detects_truncated_database(tmp_path: Path) -> None:
    db, conn, session, _backup, _ids, _clock = _open(tmp_path)
    conn.close()
    db.write_bytes(db.read_bytes()[:64])
    with pytest.raises(DatabaseCorruptionError, match="повреждён"):
        prepare_database_startup(db)


@pytest.mark.acceptance
def test_startup_cleans_stale_partial(tmp_path: Path) -> None:
    db, conn, session, _backup, _ids, _clock = _open(tmp_path)
    conn.close()
    partial = db.with_name(db.name + ".partial")
    partial.write_bytes(b"stale")
    actions = prepare_database_startup(db)
    assert not partial.exists()
    assert actions
    conn2 = connect(db, session.master_key)
    conn2.close()


@pytest.mark.acceptance
def test_technical_events_contain_no_secrets(tmp_path: Path) -> None:
    db, conn, session, backup, _ids, _clock = _open(tmp_path)
    backup.create_backup(tmp_path / "copy")
    rows = conn.execute(
        "SELECT event_type, message FROM technical_events WHERE event_type LIKE 'backup.%'"
    ).fetchall()
    assert rows
    blob = " ".join(f"{r[0]} {r[1]}" for r in rows).lower()
    assert "adminpass" not in blob
    assert "password" not in blob
    assert session.master_key.hex() not in blob
    conn.close()


@pytest.mark.acceptance
def test_relogin_after_restore(tmp_path: Path) -> None:
    db, conn, session, backup, ids, clock = _open(tmp_path)
    snapshot = backup.create_backup(tmp_path / "snap")
    new_conn = backup.restore_backup(snapshot)
    new_conn.close()
    auth = AuthenticationService(clock=clock)
    conn2, session2 = auth.login(db_path=db, login="admin", password="AdminPass-1")
    row = conn2.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()
    assert row[0] == "Иванов Иван Иванович"
    conn2.close()
