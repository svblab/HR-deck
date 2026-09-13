"""Integration: transport authoritative state survives backup/restore (EPIC-019 / ADR-0007)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from data.db import Connection
from data.transport_crypto import generate_bootstrap_keypair, generate_signing_keypair
from domain.transport import WkRole
from services.backup import BackupService
from services.bootstrap import BootstrapService
from services.transport_keys import TransportKeyStore
from tests.fixtures.synthetic import seed_synthetic_org


def _fixed_clock() -> str:
    return "2026-09-12T10:00:00Z"


def _capture_transport_state(conn: Connection) -> dict[str, list[tuple[Any, ...]]]:
    """Full transport table snapshots for byte-level equality checks."""
    return {
        "installation": conn.execute(
            "SELECT installation_id, display_label, created_at, updated_at"
            " FROM transport_installation ORDER BY installation_id"
        ).fetchall(),
        "signing_keys": conn.execute(
            "SELECT key_fingerprint, public_key, private_key, key_status, created_at,"
            " superseded_at, notes"
            " FROM transport_local_signing_keys ORDER BY id"
        ).fetchall(),
        "bootstrap_keys": conn.execute(
            "SELECT key_fingerprint, public_key, private_key, key_status, created_at,"
            " superseded_at, notes"
            " FROM transport_local_bootstrap_keys ORDER BY id"
        ).fetchall(),
        "peer_trust": conn.execute(
            "SELECT peer_installation_id, display_label,"
            " signing_public_key, signing_key_fingerprint, signing_trust_status,"
            " bootstrap_public_key, bootstrap_key_fingerprint, bootstrap_trust_status,"
            " trusted_at, revoked_at, notes"
            " FROM transport_peer_trust ORDER BY id"
        ).fetchall(),
        "direction_state": conn.execute(
            "SELECT sender_installation_id, recipient_installation_id, peer_trust_id,"
            " accepted_sequence, current_wk_id, direction_status, created_at, updated_at"
            " FROM transport_direction_state ORDER BY id"
        ).fetchall(),
        "wk_keys": conn.execute(
            "SELECT key_id, direction_id, sequence_established, wk_key_material, wk_role,"
            " predecessor_key_id, created_at, retired_at"
            " FROM transport_wk_keys ORDER BY id"
        ).fetchall(),
        "package_records": conn.execute(
            "SELECT direction_id, package_id, sequence, classification, rejection_reason,"
            " envelope_key_id, first_seen_at, last_seen_at, accepted_at"
            " FROM transport_package_records ORDER BY id"
        ).fetchall(),
    }


def _seed_transport_state(conn: Connection) -> dict[str, Any]:
    store = TransportKeyStore(conn, clock=_fixed_clock)
    local = store.ensure_local_installation(display_label="Local site")
    signing_fp = store.generate_local_signing_identity()
    bootstrap_fp = store.generate_local_bootstrap_identity()

    peer_signing = generate_signing_keypair()
    peer_bootstrap = generate_bootstrap_keypair()
    peer_installation_id = str(uuid.uuid4())
    peer_trust_id = store.register_peer_trust(
        peer_installation_id=peer_installation_id,
        display_label="Remote peer",
        signing_public_key=peer_signing.public_key,
        signing_fingerprint=peer_signing.fingerprint,
        bootstrap_public_key=peer_bootstrap.public_key,
        bootstrap_fingerprint=peer_bootstrap.fingerprint,
    )
    direction = store.ensure_direction(
        sender_installation_id=peer_installation_id,
        recipient_installation_id=local.installation_id,
        peer_trust_id=peer_trust_id,
    )
    next_wk = store.create_wk_key(direction_id=direction.id, wk_role=WkRole.HISTORICAL)
    store.record_package_acceptance(
        direction_id=direction.id,
        package_id="pkg-transport-backup-1",
        sequence=1,
        envelope_key_id="wk-envelope-1",
        next_wk=next_wk,
        accepted_sequence=1,
    )
    conn.commit()
    return {
        "signing_fp": signing_fp,
        "bootstrap_fp": bootstrap_fp,
        "peer_installation_id": peer_installation_id,
        "wk_key_id": next_wk.key_id,
    }


@pytest.mark.acceptance
def test_transport_state_survives_backup_restore(tmp_path: Path) -> None:
    """ADR-0007: authoritative transport tables in personnel.db survive whole-file backup."""
    clock = _fixed_clock
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    seed_synthetic_org(conn)
    markers = _seed_transport_state(conn)
    before = _capture_transport_state(conn)

    backup = BackupService(conn, session, db_path=db, clock=clock)
    snapshot = backup.create_backup(tmp_path / "external")

    conn.execute(
        "UPDATE transport_wk_keys SET wk_role = 'compromised' WHERE key_id = ?",
        (markers["wk_key_id"],),
    )
    conn.execute(
        "UPDATE transport_local_signing_keys SET key_status = 'lost' WHERE key_status = 'active'"
    )
    conn.commit()

    restored = backup.restore_backup(snapshot)
    after = _capture_transport_state(restored)

    assert after == before
    assert after["signing_keys"][0][0] == markers["signing_fp"]
    assert after["bootstrap_keys"][0][0] == markers["bootstrap_fp"]
    assert after["wk_keys"][0][0] == markers["wk_key_id"]
    assert after["wk_keys"][0][3]  # wk_key_material blob
    assert after["signing_keys"][0][2]  # signing private_key blob
    assert after["package_records"][0][1] == "pkg-transport-backup-1"
    restored.close()
