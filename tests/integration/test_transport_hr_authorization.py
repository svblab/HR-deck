"""PR-AUD-001: HR transport import/export uses IMPORT_EXPORT (ADR-0007 §Права)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from data.transport_crypto import generate_bootstrap_keypair, generate_signing_keypair
from domain.directory_sync import DirectorySyncPackage
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.directory_sync import DirectorySyncService
from services.directory_sync_import import DirectorySyncImportService
from services.transport_key_admin import TransportKeyAdminService
from services.transport_keys import TransportKeyStore

_T0 = "2026-09-29T12:00:00Z"


def _admin_setup(tmp_path: Path):
    db = tmp_path / "app.db"
    conn, admin_sess, _code = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return db, conn, admin_sess


def _hr_session(db: Path, conn, admin_sess):
    mgr = AccountManagementService(conn, admin_sess, db_path=db, clock=lambda: _T0)
    mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    conn.close()
    conn, hr_sess = AuthenticationService().login(db_path=db, login="hr1", password="HrPass-1")
    return conn, hr_sess


def _direction_id(conn) -> int:
    store = TransportKeyStore(conn, clock=lambda: _T0)
    local = store.ensure_local_installation(display_label="Local")
    signing = generate_signing_keypair()
    bootstrap = generate_bootstrap_keypair()
    peer_installation_id = str(uuid.uuid4())
    peer_id = store.register_peer_trust(
        peer_installation_id=peer_installation_id,
        display_label="Peer",
        signing_public_key=signing.public_key,
        signing_fingerprint=signing.fingerprint,
        bootstrap_public_key=bootstrap.public_key,
        bootstrap_fingerprint=bootstrap.fingerprint,
    )
    direction = store.ensure_direction(
        sender_installation_id=local.installation_id,
        recipient_installation_id=peer_installation_id,
        peer_trust_id=peer_id,
    )
    conn.commit()
    return direction.id


@pytest.mark.acceptance
def test_hr_can_build_directory_plan_for_transport_import(tmp_path: Path) -> None:
    db, conn, admin_sess = _admin_setup(tmp_path)
    conn, hr_sess = _hr_session(db, conn, admin_sess)
    pkg = DirectorySyncPackage(
        tables={"branches": [], "departments": [], "divisions": [], "positions": []}
    )
    plan = DirectorySyncImportService(conn, hr_sess).build_directory_plan(pkg)
    assert plan.is_clean
    conn.close()


@pytest.mark.acceptance
def test_hr_can_build_directory_sync_export_package(tmp_path: Path) -> None:
    db, conn, admin_sess = _admin_setup(tmp_path)
    direction_id = _direction_id(conn)
    conn, hr_sess = _hr_session(db, conn, admin_sess)
    sync = DirectorySyncService(conn, hr_sess)
    pkg = sync.build_export_package(direction_id)
    assert isinstance(pkg.tables, dict)
    conn.close()


@pytest.mark.acceptance
def test_hr_cannot_bootstrap_transport_key_admin(tmp_path: Path) -> None:
    db, conn, admin_sess = _admin_setup(tmp_path)
    conn, hr_sess = _hr_session(db, conn, admin_sess)
    admin = TransportKeyAdminService(conn, hr_sess, clock=lambda: _T0)
    with pytest.raises(AuthorizationError):
        admin.bootstrap_local_identities()
    conn.close()


@pytest.mark.acceptance
def test_observer_denied_directory_sync_import_plan(tmp_path: Path) -> None:
    db, conn, admin_sess = _admin_setup(tmp_path)
    mgr = AccountManagementService(conn, admin_sess, db_path=db, clock=lambda: _T0)
    mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    conn.close()
    conn, obs_sess = AuthenticationService().login(db_path=db, login="obs1", password="ObsPass-1")
    pkg = DirectorySyncPackage(
        tables={"branches": [], "departments": [], "divisions": [], "positions": []}
    )
    with pytest.raises(AuthorizationError):
        DirectorySyncImportService(conn, obs_sess).build_directory_plan(pkg)
    conn.close()
