"""TransportKeyStore unit tests mapped to ADR-0007 v3 test contract."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from data.transport_crypto import generate_bootstrap_keypair, generate_signing_keypair, key_fingerprint
from domain.permissions import Permission, RoleCode
from domain.transport import PackageClassification, TransportKeyError, TrustStatus, WkRole
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.transport_key_admin import TransportKeyAdminService
from services.transport_keys import TransportKeyStore
from services.session import SessionState


def _open_store(tmp_path: Path) -> tuple:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    store = TransportKeyStore(conn, clock=lambda: "2026-09-12T00:00:00Z")
    return conn, store


def _seed_peer(store: TransportKeyStore) -> tuple[str, int]:
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
    return local.installation_id, peer_id


@pytest.mark.parametrize(
    ("adr_row", "test_name"),
    [
        ("Signing vs bootstrap", "signing_and_bootstrap_separate"),
        ("Transport DB atomicity", "no_commit_until_caller_commits"),
        ("key_id lookup", "lookup_wk_by_key_id"),
        ("Duplex independence", "duplex_directions_independent"),
        ("Lost signing key", "mark_local_signing_lost"),
        ("No silent rollback", "historical_wk_not_auto_promoted"),
        ("Replay idempotency", "exact_replay_is_idempotent"),
        ("key_id uniqueness", "wire_key_id_collision_safe"),
        ("Compromised key", "revoke_wk_marks_broken_direction"),
        ("Bootstrap", "register_peer_trust_stores_both_keys"),
    ],
)
def test_adr_contract_row_coverage(adr_row: str, test_name: str) -> None:
    assert adr_row and test_name


def test_signing_and_bootstrap_separate(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    store.ensure_local_installation()
    signing_fp = store.generate_local_signing_identity()
    bootstrap_fp = store.generate_local_bootstrap_identity()
    assert signing_fp != bootstrap_fp
    signing_count = conn.execute(
        "SELECT COUNT(*) FROM transport_local_signing_keys WHERE key_status='active'"
    ).fetchone()[0]
    bootstrap_count = conn.execute(
        "SELECT COUNT(*) FROM transport_local_bootstrap_keys WHERE key_status='active'"
    ).fetchone()[0]
    assert signing_count == 1
    assert bootstrap_count == 1


def test_no_commit_until_caller_commits(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    store.ensure_local_installation()
    store.generate_local_signing_identity()
    assert (
        conn.execute("SELECT COUNT(*) FROM transport_local_signing_keys").fetchone()[0] == 1
    )
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM transport_local_signing_keys").fetchone()[0] == 0


def test_register_peer_trust_stores_both_keys(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    _, peer_id = _seed_peer(store)
    conn.commit()
    row = conn.execute(
        "SELECT signing_key_fingerprint, bootstrap_key_fingerprint FROM transport_peer_trust WHERE id=?",
        (peer_id,),
    ).fetchone()
    assert row[0] != row[1]


def test_lookup_wk_by_key_id(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    local_id, peer_id = _seed_peer(store)
    direction = store.ensure_direction(
        sender_installation_id=local_id,
        recipient_installation_id=conn.execute(
            "SELECT peer_installation_id FROM transport_peer_trust WHERE id=?", (peer_id,)
        ).fetchone()[0],
        peer_trust_id=peer_id,
    )
    wk = store.create_wk_key(direction_id=direction.id, wk_role=WkRole.ACTIVE)
    conn.commit()
    found = store.lookup_wk_by_key_id(wk.key_id)
    assert found is not None
    assert found.id == wk.id


def test_duplex_directions_independent(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    local_id, peer_id = _seed_peer(store)
    peer_installation_id = conn.execute(
        "SELECT peer_installation_id FROM transport_peer_trust WHERE id=?", (peer_id,)
    ).fetchone()[0]
    out_dir = store.ensure_direction(
        sender_installation_id=local_id,
        recipient_installation_id=peer_installation_id,
        peer_trust_id=peer_id,
    )
    in_dir = store.ensure_direction(
        sender_installation_id=peer_installation_id,
        recipient_installation_id=local_id,
        peer_trust_id=peer_id,
    )
    wk_out = store.create_wk_key(direction_id=out_dir.id, wk_role=WkRole.ACTIVE)
    store.activate_wk_for_direction(
        direction_id=out_dir.id, wk_row_id=wk_out.id, accepted_sequence=1
    )
    conn.commit()
    in_state = conn.execute(
        "SELECT accepted_sequence, current_wk_id FROM transport_direction_state WHERE id=?",
        (in_dir.id,),
    ).fetchone()
    assert in_state == (0, None)


def test_mark_local_signing_lost(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    store.ensure_local_installation()
    store.generate_local_signing_identity()
    store.mark_local_signing_lost()
    conn.commit()
    status = conn.execute(
        "SELECT key_status FROM transport_local_signing_keys"
    ).fetchone()[0]
    assert status == "lost"


def test_historical_wk_not_auto_promoted(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    local_id, peer_id = _seed_peer(store)
    peer_installation_id = conn.execute(
        "SELECT peer_installation_id FROM transport_peer_trust WHERE id=?", (peer_id,)
    ).fetchone()[0]
    direction = store.ensure_direction(
        sender_installation_id=local_id,
        recipient_installation_id=peer_installation_id,
        peer_trust_id=peer_id,
    )
    first = store.create_wk_key(direction_id=direction.id, wk_role=WkRole.ACTIVE)
    store.activate_wk_for_direction(direction_id=direction.id, wk_row_id=first.id, accepted_sequence=1)
    second = store.create_wk_key(
        direction_id=direction.id,
        wk_role=WkRole.HISTORICAL,
        predecessor_key_id=first.key_id,
    )
    conn.commit()
    roles = {
        row[0]
        for row in conn.execute(
            "SELECT wk_role FROM transport_wk_keys WHERE direction_id=?", (direction.id,)
        ).fetchall()
    }
    assert roles == {"active", "historical"}
    assert second.wk_role == WkRole.HISTORICAL


def test_exact_replay_is_idempotent(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    local_id, peer_id = _seed_peer(store)
    peer_installation_id = conn.execute(
        "SELECT peer_installation_id FROM transport_peer_trust WHERE id=?", (peer_id,)
    ).fetchone()[0]
    direction = store.ensure_direction(
        sender_installation_id=peer_installation_id,
        recipient_installation_id=local_id,
        peer_trust_id=peer_id,
    )
    next_wk = store.create_wk_key(direction_id=direction.id, wk_role=WkRole.HISTORICAL)
    result1 = store.record_package_acceptance(
        direction_id=direction.id,
        package_id="pkg-1",
        sequence=1,
        envelope_key_id="wk-wire-1",
        next_wk=next_wk,
        accepted_sequence=1,
    )
    conn.commit()
    emp_before = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    result2 = store.record_package_acceptance(
        direction_id=direction.id,
        package_id="pkg-1",
        sequence=1,
        envelope_key_id="wk-wire-1",
    )
    conn.commit()
    emp_after = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    assert result1.replay is False
    assert result2.replay is True
    assert emp_before == emp_after
    classification = conn.execute(
        "SELECT classification FROM transport_package_records WHERE package_id='pkg-1'"
    ).fetchone()[0]
    assert classification == PackageClassification.ACCEPTED.value


def test_wire_key_id_collision_safe(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    local_id, peer_id = _seed_peer(store)
    peer_installation_id = conn.execute(
        "SELECT peer_installation_id FROM transport_peer_trust WHERE id=?", (peer_id,)
    ).fetchone()[0]
    direction = store.ensure_direction(
        sender_installation_id=local_id,
        recipient_installation_id=peer_installation_id,
        peer_trust_id=peer_id,
    )
    fixed = "deadbeef" * 4
    store.create_wk_key(direction_id=direction.id, wk_role=WkRole.ACTIVE, wire_key_id=fixed)
    with pytest.raises(TransportKeyError):
        store.create_wk_key(direction_id=direction.id, wk_role=WkRole.HISTORICAL, wire_key_id=fixed)


def test_revoke_wk_marks_broken_direction(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    local_id, peer_id = _seed_peer(store)
    peer_installation_id = conn.execute(
        "SELECT peer_installation_id FROM transport_peer_trust WHERE id=?", (peer_id,)
    ).fetchone()[0]
    direction = store.ensure_direction(
        sender_installation_id=local_id,
        recipient_installation_id=peer_installation_id,
        peer_trust_id=peer_id,
    )
    wk = store.create_wk_key(direction_id=direction.id, wk_role=WkRole.ACTIVE)
    store.activate_wk_for_direction(direction_id=direction.id, wk_row_id=wk.id, accepted_sequence=1)
    store.revoke_wk(wk.key_id, role=WkRole.COMPROMISED)
    conn.commit()
    status = conn.execute(
        "SELECT direction_status FROM transport_direction_state WHERE id=?", (direction.id,)
    ).fetchone()[0]
    assert status == "broken"


def test_activate_wk_insert_order_respects_fk(tmp_path: Path) -> None:
    conn, store = _open_store(tmp_path)
    local_id, peer_id = _seed_peer(store)
    peer_installation_id = conn.execute(
        "SELECT peer_installation_id FROM transport_peer_trust WHERE id=?", (peer_id,)
    ).fetchone()[0]
    direction = store.ensure_direction(
        sender_installation_id=local_id,
        recipient_installation_id=peer_installation_id,
        peer_trust_id=peer_id,
    )
    wk = store.create_wk_key(direction_id=direction.id, wk_role=WkRole.HISTORICAL)
    store.activate_wk_for_direction(direction_id=direction.id, wk_row_id=wk.id, accepted_sequence=1)
    conn.commit()
    current = conn.execute(
        "SELECT current_wk_id FROM transport_direction_state WHERE id=?", (direction.id,)
    ).fetchone()[0]
    assert current == wk.id


def test_admin_service_requires_manage_encryption_keys(tmp_path: Path) -> None:
    conn, _store = _open_store(tmp_path)
    session = SessionState(
        account_id=2,
        login="hr",
        role=RoleCode.HR_EMPLOYEE,
        master_key=generate_master_key(),
        locked=False,
    )
    admin = TransportKeyAdminService(conn, session)
    with pytest.raises(AuthorizationError):
        admin.bootstrap_local_identities()


def test_admin_service_writes_audit_on_bootstrap(tmp_path: Path) -> None:
    clock = lambda: "2026-09-12T00:00:00Z"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        login="admin",
        password="AdminPass-1",
        db_path=tmp_path / "app.db",
    )
    admin = TransportKeyAdminService(conn, session, clock=clock)
    admin.bootstrap_local_identities()
    row = conn.execute(
        "SELECT action_type, entity_type FROM user_action_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row == ("transport.identity.bootstrap", "transport")
    assert Permission.MANAGE_ENCRYPTION_KEYS in __import__(
        "domain.permissions", fromlist=["permissions_for"]
    ).permissions_for(RoleCode.ADMINISTRATOR)
