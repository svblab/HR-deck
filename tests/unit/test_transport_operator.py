"""TransportOperatorService (Issue #130 / ADR-0016)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from data.transport_crypto import generate_bootstrap_keypair, generate_signing_keypair
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.transport_keys import TransportKeyStore
from services.transport_operator import TransportOperatorService

_T0 = "2026-09-29T14:00:00Z"


def _bootstrap_direction(store: TransportKeyStore, conn) -> int:
    local = store.ensure_local_installation(display_label="Local")
    store.generate_local_signing_identity()
    store.generate_local_bootstrap_identity()
    signing = generate_signing_keypair()
    bootstrap = generate_bootstrap_keypair()
    peer_installation_id = str(uuid.uuid4())
    peer_id = store.register_peer_trust(
        peer_installation_id=peer_installation_id,
        display_label="Peer A",
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


def _hr_session(tmp_path: Path):
    db = tmp_path / "app.db"
    conn, admin, _ = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    mgr = AccountManagementService(conn, admin, db_path=db, clock=lambda: _T0)
    mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    conn.close()
    conn, hr = AuthenticationService().login(db_path=db, login="hr1", password="HrPass-1")
    return conn, hr, db


@pytest.mark.acceptance
def test_list_outbound_targets_for_hr(tmp_path: Path) -> None:
    conn, hr, _db = _hr_session(tmp_path)
    store = TransportKeyStore(conn, clock=lambda: _T0)
    direction_id = _bootstrap_direction(store, conn)
    svc = TransportOperatorService(conn, hr, store=store)
    targets = svc.list_outbound_export_targets()
    assert len(targets) == 1
    assert targets[0].direction_id == direction_id
    assert targets[0].peer_label == "Peer A"
    conn.close()


@pytest.mark.acceptance
def test_hr_export_personnel_package_writes_wire_bytes(tmp_path: Path) -> None:
    conn, hr, _db = _hr_session(tmp_path)
    store = TransportKeyStore(conn, clock=lambda: _T0)
    direction_id = _bootstrap_direction(store, conn)
    directories = DirectoryService(conn, hr, clock=lambda: _T0)
    directories.create_branch("Филиал экспорт")
    conn.commit()
    svc = TransportOperatorService(conn, hr, store=store)
    result = svc.export_personnel_package(direction_id)
    assert result.export.wire_bytes
    assert result.export.package_id
    assert "branches" in result.tables_exported
    conn.close()


@pytest.mark.acceptance
def test_observer_cannot_list_outbound_targets(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    conn, admin, _ = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    mgr = AccountManagementService(conn, admin, db_path=db, clock=lambda: _T0)
    mgr.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    conn.close()
    conn, obs = AuthenticationService().login(db_path=db, login="obs1", password="ObsPass-1")
    svc = TransportOperatorService(conn, obs)
    with pytest.raises(AuthorizationError):
        svc.list_outbound_export_targets()
    conn.close()
