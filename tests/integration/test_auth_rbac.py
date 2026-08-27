"""Integration: bootstrap, login, lock, recovery, accounts, audit (EPIC-003)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.accounts import AccountRepository
from data.db import connect
from data.keywrap import keywrap_path_for, load_keywrap
from domain.password_kdf import hash_password
from domain.permissions import RoleCode
from services.account_management import AccountManagementError, AccountManagementService
from services.authentication import AuthenticationError, AuthenticationService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapError, BootstrapService
from services.session import SessionLockedError


@pytest.fixture
def sleepless_auth() -> AuthenticationService:
    delays: list[float] = []

    def _sleep(seconds: float) -> None:
        delays.append(seconds)

    svc = AuthenticationService(sleeper=_sleep)
    svc.delays = delays  # type: ignore[attr-defined]
    return svc


def _setup(tmp_path: Path) -> tuple[Path, object, object, str]:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-26T12:00:00Z")
    conn, session, code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return db, conn, session, code


@pytest.mark.acceptance
def test_initial_setup_creates_admin_and_one_time_recovery(tmp_path: Path) -> None:
    db, conn, session, code = _setup(tmp_path)
    assert session.login == "admin"
    assert session.role == RoleCode.ADMINISTRATOR
    assert keywrap_path_for(db).is_file()
    assert AccountRepository(conn).count_administrators() == 1
    # recovery plaintext not in DB bytes as UTF-8 (best-effort) nor in audit details
    raw_db = db.read_bytes()
    assert code.encode("utf-8") not in raw_db
    rows = conn.execute("SELECT details FROM user_action_log").fetchall()
    events = conn.execute("SELECT message FROM technical_events").fetchall()
    blob = " ".join(str(x) for row in rows + events for x in row)
    assert code not in blob
    assert "AdminPass-1" not in blob
    conn.close()


@pytest.mark.acceptance
def test_login_success_and_failure(tmp_path: Path, sleepless_auth: AuthenticationService) -> None:
    db, conn, _session, _code = _setup(tmp_path)
    conn.close()

    c2, s2 = sleepless_auth.login(db_path=db, login="admin", password="AdminPass-1")
    assert s2.account_id == 1
    c2.close()

    with pytest.raises(AuthenticationError):
        sleepless_auth.login(db_path=db, login="admin", password="wrong")
    assert sleepless_auth.delays  # type: ignore[attr-defined]

    with pytest.raises(AuthenticationError):
        sleepless_auth.login(db_path=db, login="nosuch", password="wrong")
    assert len(sleepless_auth.delays) >= 2  # type: ignore[attr-defined]


@pytest.mark.acceptance
def test_disabled_account_rejected(tmp_path: Path, sleepless_auth: AuthenticationService) -> None:
    db, conn, session, _code = _setup(tmp_path)
    mgr = AccountManagementService(conn, session, db_path=db, clock=lambda: "2026-08-26T12:01:00Z")
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    mgr.set_active(hr_id, False)
    conn.close()

    with pytest.raises(AuthenticationError):
        sleepless_auth.login(db_path=db, login="hr1", password="HrPass-1")


@pytest.mark.acceptance
def test_session_lock_and_unlock(tmp_path: Path, sleepless_auth: AuthenticationService) -> None:
    db, conn, session, _code = _setup(tmp_path)
    original_key = session.master_key
    session.lock(clear_key=True)
    assert session.master_key == b""
    with pytest.raises(SessionLockedError):
        session.require_unlocked()
    conn.close()
    conn = sleepless_auth.unlock(
        session,
        "AdminPass-1",
        db_path=db,
    )
    assert session.master_key == original_key
    session.require_unlocked()
    session.lock(clear_key=True)
    with pytest.raises(AuthenticationError):
        sleepless_auth.unlock(session, "bad", db_path=db)
    conn.close()


@pytest.mark.acceptance
def test_recovery_valid_invalid_reuse(
    tmp_path: Path,
    sleepless_auth: AuthenticationService,
) -> None:
    db, conn, _session, code = _setup(tmp_path)
    conn.close()

    with pytest.raises(BootstrapError):
        BootstrapService().recover_administrator_password(
            db_path=db, recovery_code="not-the-code", new_password="NewAdmin-2"
        )

    new_code = BootstrapService().recover_administrator_password(
        db_path=db, recovery_code=code, new_password="NewAdmin-2"
    )
    assert new_code != code
    wrap_after = load_keywrap(keywrap_path_for(db))
    recovery_wraps = [w for w in wrap_after.wraps if w.kind == "recovery"]
    assert len(recovery_wraps) == 1

    with pytest.raises(BootstrapError):
        BootstrapService().recover_administrator_password(
            db_path=db, recovery_code=code, new_password="Another-3"
        )

    BootstrapService().recover_administrator_password(
        db_path=db, recovery_code=new_code, new_password="NewAdmin-3"
    )

    c2, s2 = sleepless_auth.login(db_path=db, login="admin", password="NewAdmin-3")
    assert s2.login == "admin"
    c2.close()


@pytest.mark.acceptance
def test_account_management_rbac_and_audit(tmp_path: Path) -> None:
    db, conn, session, _code = _setup(tmp_path)
    clock = {"t": 0}

    def now() -> str:
        clock["t"] += 1
        return f"2026-08-26T13:00:{clock['t']:02d}Z"

    admin_mgr = AccountManagementService(conn, session, db_path=db, clock=now)
    hr_id = admin_mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    obs_id = admin_mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)

    # ensure create audited
    rows = conn.execute(
        "SELECT action_type, result FROM user_action_log WHERE entity_id = ?", (hr_id,)
    ).fetchall()
    assert ("account.create", "success") in {(r[0], r[1]) for r in rows}

    # HR cannot manage accounts
    from data.accounts import AccountRepository

    hr = AccountRepository(conn).get_by_id(hr_id)
    assert hr is not None
    hr_session = type(session)(
        account_id=hr.id,
        login=hr.login,
        role=RoleCode.HR_EMPLOYEE,
        master_key=session.master_key,
    )
    hr_mgr = AccountManagementService(conn, hr_session, db_path=db, clock=now)
    with pytest.raises(AuthorizationError):
        hr_mgr.create_account(login="x", password="y", role=RoleCode.OBSERVER)

    obs = AccountRepository(conn).get_by_id(obs_id)
    assert obs is not None
    obs_session = type(session)(
        account_id=obs.id,
        login=obs.login,
        role=RoleCode.OBSERVER,
        master_key=session.master_key,
    )
    obs_mgr = AccountManagementService(conn, obs_session, db_path=db, clock=now)
    with pytest.raises(AuthorizationError):
        obs_mgr.set_role(hr_id, RoleCode.ADMINISTRATOR)

    # role escalation via service denied for non-admin; admin can set but last admin protected
    with pytest.raises(AccountManagementError):
        admin_mgr.set_role(session.account_id, RoleCode.HR_EMPLOYEE)

    conn.close()


@pytest.mark.acceptance
def test_failed_mutation_no_success_audit(tmp_path: Path) -> None:
    db, conn, session, _code = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T14:00:00Z"
    )
    before = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    with pytest.raises(AccountManagementError):
        mgr.create_account(login="admin", password="dup", role=RoleCode.HR_EMPLOYEE)
    after = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after == before
    conn.close()


def test_keywrap_has_no_plaintext_master_key(tmp_path: Path) -> None:
    db, conn, session, _code = _setup(tmp_path)
    wrap = load_keywrap(keywrap_path_for(db))
    text = keywrap_path_for(db).read_text(encoding="utf-8")
    assert session.master_key.hex() not in text
    assert any(w.kind == "recovery" for w in wrap.wraps)
    conn.close()


def test_cannot_create_or_promote_second_active_administrator(tmp_path: Path) -> None:
    db, conn, session, _code = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T15:00:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)

    with pytest.raises(AccountManagementError, match="only one active administrator"):
        mgr.create_account(login="admin2", password="AdminPass-2", role=RoleCode.ADMINISTRATOR)

    with pytest.raises(AccountManagementError, match="only one active administrator"):
        mgr.set_role(hr_id, RoleCode.ADMINISTRATOR)

    with pytest.raises(AccountManagementError, match="cannot disable the last administrator"):
        mgr.set_active(session.account_id, False)

    assert AccountRepository(conn).count_active_administrators() == 1
    conn.close()


def test_cannot_reactivate_second_administrator(tmp_path: Path) -> None:
    db, conn, session, _code = _setup(tmp_path)
    mgr = AccountManagementService(
        conn, session, db_path=db, clock=lambda: "2026-08-26T15:10:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    accounts = AccountRepository(conn)
    accounts.set_role(hr_id, RoleCode.ADMINISTRATOR, "2026-08-26T15:11:00Z")
    accounts.set_active(hr_id, False, "2026-08-26T15:12:00Z")
    conn.commit()

    with pytest.raises(AccountManagementError, match="only one active administrator"):
        mgr.set_active(hr_id, True)

    assert accounts.count_active_administrators() == 1
    conn.close()


def test_recovery_fails_with_two_active_administrators_without_changing_passwords(
    tmp_path: Path,
    sleepless_auth: AuthenticationService,
) -> None:
    db, conn, session, code = _setup(tmp_path)
    accounts = AccountRepository(conn)
    accounts.create(
        login="aaa",
        password_hash=hash_password("AaaPass-1"),
        role=RoleCode.ADMINISTRATOR,
        created_at="2026-08-26T12:00:00Z",
    )
    conn.commit()
    admin_hash = accounts.get_by_login("admin")
    aaa_hash = accounts.get_by_login("aaa")
    assert admin_hash is not None and aaa_hash is not None
    admin_hash_before = admin_hash.password_hash
    aaa_hash_before = aaa_hash.password_hash
    master_key = session.master_key
    conn.close()

    with pytest.raises(BootstrapError, match="multiple active administrators"):
        BootstrapService().recover_administrator_password(
            db_path=db, recovery_code=code, new_password="Hacked-99"
        )

    conn = connect(db, master_key)
    after_admin = AccountRepository(conn).get_by_login("admin")
    after_aaa = AccountRepository(conn).get_by_login("aaa")
    assert after_admin is not None and after_aaa is not None
    assert after_admin.password_hash == admin_hash_before
    assert after_aaa.password_hash == aaa_hash_before
    conn.close()

    c2, _s2 = sleepless_auth.login(db_path=db, login="admin", password="AdminPass-1")
    c2.close()


def test_recovery_fails_when_administrator_is_inactive_without_changing_password(
    tmp_path: Path,
) -> None:
    db, conn, session, code = _setup(tmp_path)
    accounts = AccountRepository(conn)
    admin = accounts.get_by_login("admin")
    assert admin is not None
    hash_before = admin.password_hash
    accounts.set_active(admin.id, False, "2026-08-26T16:00:00Z")
    conn.commit()
    master_key = session.master_key
    conn.close()

    with pytest.raises(BootstrapError, match="no active administrator"):
        BootstrapService().recover_administrator_password(
            db_path=db, recovery_code=code, new_password="Hacked-99"
        )

    conn = connect(db, master_key)
    after = AccountRepository(conn).get_by_id(admin.id)
    assert after is not None
    assert after.password_hash == hash_before
    assert not after.is_active
    consumed = conn.execute(
        "SELECT COUNT(*) FROM recovery_codes WHERE is_consumed = 1"
    ).fetchone()
    assert consumed is not None
    assert int(consumed[0]) == 0
    conn.close()


def test_plaintext_password_not_stored_in_accounts(tmp_path: Path) -> None:
    db, conn, _session, _code = _setup(tmp_path)
    row = conn.execute("SELECT password_hash, password_salt FROM accounts").fetchone()
    assert row is not None
    assert "AdminPass-1" not in row[0]
    assert row[0].startswith("$argon2")
    conn.close()
