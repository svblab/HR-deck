"""Integration: account CRUD, password reset, security settings, keywrap atomicity."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.accounts import AccountRepository
from data.keywrap import (
    KeywrapError,
    find_account_wrap,
    keywrap_path_for,
    load_keywrap,
    unwrap_secret,
)
from domain.permissions import RoleCode
from services.account_management import AccountManagementError, AccountManagementService
from services.authentication import AuthenticationError, AuthenticationService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.session import SessionState


def _setup(tmp_path: Path) -> tuple[Path, object, SessionState]:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-26T12:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return db, conn, session


def _sleepless_auth() -> AuthenticationService:
    def _sleep(_seconds: float) -> None:
        return None

    return AuthenticationService(sleeper=_sleep)


def _hr_session(conn: object, session: SessionState, hr_id: int) -> SessionState:
    hr = AccountRepository(conn).get_by_id(hr_id)  # type: ignore[arg-type]
    assert hr is not None
    return SessionState(
        account_id=hr.id,
        login=hr.login,
        role=RoleCode.HR_EMPLOYEE,
        master_key=session.master_key,
    )


def test_reset_password_happy_path(tmp_path: Path) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T17:00:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    before = AccountRepository(conn).get_by_id(hr_id)
    assert before is not None
    hash_before = before.password_hash

    mgr.reset_password(hr_id, "HrPass-2")

    after = AccountRepository(conn).get_by_id(hr_id)
    assert after is not None
    assert after.password_hash != hash_before
    rows = conn.execute(  # type: ignore[union-attr]
        "SELECT action_type, result FROM user_action_log WHERE entity_id = ? AND action_type = ?",
        (hr_id, "account.reset_password"),
    ).fetchall()
    assert ("account.reset_password", "success") in {(r[0], r[1]) for r in rows}

    wrap = load_keywrap(keywrap_path_for(db))
    entry = find_account_wrap(wrap, "hr1")
    assert entry is not None
    assert unwrap_secret(entry, "HrPass-2") == session.master_key
    with pytest.raises(KeywrapError):
        unwrap_secret(entry, "HrPass-1")

    conn.close()  # type: ignore[union-attr]
    auth = _sleepless_auth()
    c2, s2 = auth.login(db_path=db, login="hr1", password="HrPass-2")
    assert s2.login == "hr1"
    c2.close()
    with pytest.raises(AuthenticationError):
        auth.login(db_path=db, login="hr1", password="HrPass-1")


def test_reset_password_forbidden_for_non_admin(tmp_path: Path) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T17:10:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    hr_mgr = AccountManagementService(
        conn, _hr_session(conn, session, hr_id), db_path=db, clock=lambda: "2026-08-26T17:11:00Z"
    )
    with pytest.raises(AuthorizationError):
        hr_mgr.reset_password(hr_id, "HrPass-2")
    conn.close()  # type: ignore[union-attr]


def test_reset_password_empty_rejected(tmp_path: Path) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T17:20:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    with pytest.raises(AccountManagementError, match="password is required"):
        mgr.reset_password(hr_id, "")
    conn.close()  # type: ignore[union-attr]


def test_reset_password_missing_account(tmp_path: Path) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T17:30:00Z"
    )
    with pytest.raises(AccountManagementError, match="account not found"):
        mgr.reset_password(9_999, "Whatever-1")
    conn.close()  # type: ignore[union-attr]


def test_security_settings_round_trip_and_audit(tmp_path: Path) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T18:00:00Z"
    )
    mgr.update_security_settings(
        inactivity_timeout_seconds=120,
        inactivity_timeout_enabled=False,
        login_failure_delay_seconds=5,
        login_failure_delay_enabled=False,
    )
    got = mgr.get_security_settings()
    assert got == {
        "inactivity_timeout_seconds": 120,
        "inactivity_timeout_enabled": False,
        "login_failure_delay_seconds": 5,
        "login_failure_delay_enabled": False,
    }
    assert session.inactivity_timeout_seconds == 120
    assert session.inactivity_timeout_enabled is False
    rows = conn.execute(  # type: ignore[union-attr]
        "SELECT action_type, result, entity_type FROM user_action_log "
        "WHERE action_type = ?",
        ("security.settings_update",),
    ).fetchall()
    assert ("security.settings_update", "success", "app_settings") in {
        (r[0], r[1], r[2]) for r in rows
    }
    conn.close()  # type: ignore[union-attr]


def test_security_settings_reject_negative_values(tmp_path: Path) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T18:10:00Z"
    )
    with pytest.raises(AccountManagementError, match="invalid inactivity timeout"):
        mgr.update_security_settings(inactivity_timeout_seconds=-1)
    with pytest.raises(AccountManagementError, match="invalid login delay"):
        mgr.update_security_settings(login_failure_delay_seconds=-1)
    got = mgr.get_security_settings()
    assert got["inactivity_timeout_seconds"] == 900
    assert got["login_failure_delay_seconds"] == 2
    conn.close()  # type: ignore[union-attr]


def test_security_settings_forbidden_for_non_admin(tmp_path: Path) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T18:20:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    hr_mgr = AccountManagementService(
        conn, _hr_session(conn, session, hr_id), db_path=db, clock=lambda: "2026-08-26T18:21:00Z"
    )
    with pytest.raises(AuthorizationError):
        hr_mgr.get_security_settings()
    with pytest.raises(AuthorizationError):
        hr_mgr.update_security_settings(inactivity_timeout_seconds=60)
    conn.close()  # type: ignore[union-attr]


def test_create_account_keywrap_failure_rolls_back_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T19:00:00Z"
    )

    def _boom(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("services.account_management.save_keywrap", _boom)
    with pytest.raises(OSError, match="disk full"):
        mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)

    assert AccountRepository(conn).get_by_login("hr1") is None  # type: ignore[arg-type]
    wrap = load_keywrap(keywrap_path_for(db))
    assert find_account_wrap(wrap, "hr1") is None
    audit = conn.execute(  # type: ignore[union-attr]
        "SELECT COUNT(*) FROM user_action_log WHERE details LIKE ?",
        ("%role=hr_employee%",),
    ).fetchone()
    assert audit is not None
    assert int(audit[0]) == 0
    conn.close()  # type: ignore[union-attr]


def test_reset_password_keywrap_failure_rolls_back_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T19:10:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    hash_before = AccountRepository(conn).get_by_id(hr_id).password_hash  # type: ignore[union-attr]

    def _boom(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("services.account_management.save_keywrap", _boom)
    with pytest.raises(OSError, match="disk full"):
        mgr.reset_password(hr_id, "HrPass-2")

    after = AccountRepository(conn).get_by_id(hr_id)
    assert after is not None
    assert after.password_hash == hash_before
    resets = conn.execute(  # type: ignore[union-attr]
        "SELECT COUNT(*) FROM user_action_log WHERE action_type = ?",
        ("account.reset_password",),
    ).fetchone()
    assert resets is not None
    assert int(resets[0]) == 0
    conn.close()  # type: ignore[union-attr]

    auth = _sleepless_auth()
    c2, _s2 = auth.login(db_path=db, login="hr1", password="HrPass-1")
    c2.close()
    with pytest.raises(AuthenticationError):
        auth.login(db_path=db, login="hr1", password="HrPass-2")


def test_list_set_role_and_set_active_for_non_admin(tmp_path: Path) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(conn, session, db_path=db)
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    mgr.set_role(hr_id, RoleCode.OBSERVER)
    mgr.set_active(hr_id, False)
    listed = {a.login: a for a in mgr.list_accounts()}
    assert listed["hr1"].role_code == RoleCode.OBSERVER.value
    assert listed["hr1"].is_active is False
    mgr.set_active(hr_id, True)
    conn.close()  # type: ignore[union-attr]


def test_create_account_requires_login_and_password(tmp_path: Path) -> None:
    db, conn, session = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T19:30:00Z"
    )
    with pytest.raises(AccountManagementError, match="login and password are required"):
        mgr.create_account(login="  ", password="x", role=RoleCode.OBSERVER)
    with pytest.raises(AccountManagementError, match="login and password are required"):
        mgr.create_account(login="obs2", password="", role=RoleCode.OBSERVER)
    conn.close()  # type: ignore[union-attr]
