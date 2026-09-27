"""Transport generation (epoch) per direction — ADR-0007 addendum matrix."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from data.transport_crypto import (
    SignatureVerificationError,
    generate_bootstrap_keypair,
    generate_signing_keypair,
    verify_signature,
)
from domain.transport import (
    BOOTSTRAP_ENVELOPE_KEY_ID,
    TRANSPORT_PROTOCOL_VERSION,
    DirectionStatus,
    TransportKeyError,
)
from services.transport_canonical import (
    build_routing_metadata_bytes,
    build_signing_bytes,
    deserialize_transport_package,
    parse_routing_metadata_bytes,
    serialize_transport_package,
)
from services.transport_export import TransportExportService
from services.transport_import_validation import (
    FreshnessClass,
    TransportImportValidationService,
    ValidationDisposition,
)
from services.transport_keys import TransportKeyStore
from services.transport_receive import DecryptedTransportPackage
from tests.unit.test_transport_export import _bootstrap_direction, _open_conn


def _decrypted(
    *,
    direction_id: int,
    generation: int,
    sequence: int,
    package_id: str,
) -> DecryptedTransportPackage:
    return DecryptedTransportPackage(
        payload=b"{}",
        sender_installation_id="sender",
        recipient_installation_id="recipient",
        direction_id=direction_id,
        generation=generation,
        sequence=sequence,
        package_id=package_id,
        envelope_key_id=BOOTSTRAP_ENVELOPE_KEY_ID,
        next_wk_key_id=str(uuid.uuid4()),
        next_wk_material=b"\x01" * 32,
    )


def test_initial_chain_g0_sequences(tmp_path: Path) -> None:
    conn, store = _open_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    exporter = TransportExportService(conn, store=store)
    r1 = exporter.export_package(direction_id=direction_id, payload=b"a")
    r2 = exporter.export_package(direction_id=direction_id, payload=b"b")
    conn.commit()
    assert r1.generation == 0 and r1.sequence == 1
    assert r2.generation == 0 and r2.sequence == 2
    assert r1.package.routing_metadata.protocol_version == TRANSPORT_PROTOCOL_VERSION


def test_reinit_bumps_generation_and_allows_g1_s1_bootstrap(tmp_path: Path) -> None:
    conn, store = _open_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    exporter = TransportExportService(conn, store=store)
    exporter.export_package(direction_id=direction_id, payload=b"g0")
    conn.commit()
    store.reinit_direction(direction_id)
    conn.commit()
    direction = store.get_direction(direction_id)
    assert direction.generation == 1
    assert direction.direction_status == DirectionStatus.REINIT_REQUIRED
    r1 = exporter.export_package(direction_id=direction_id, payload=b"g1")
    conn.commit()
    assert r1.generation == 1 and r1.sequence == 1
    assert r1.package.routing_metadata.envelope_key_id == BOOTSTRAP_ENVELOPE_KEY_ID
    assert store.get_direction(direction_id).direction_status == DirectionStatus.ACTIVE


def test_old_generation_rejected_after_reinit(tmp_path: Path) -> None:
    conn, session, store = _admin_session(tmp_path)
    direction_id = _inbound_direction(store, conn)
    store.record_package_acceptance(
        direction_id=direction_id,
        package_id=str(uuid.uuid4()),
        generation=0,
        sequence=1,
        envelope_key_id=BOOTSTRAP_ENVELOPE_KEY_ID,
        accepted_sequence=1,
    )
    store.reinit_direction(direction_id)
    conn.commit()
    svc = TransportImportValidationService(conn, session, store=store)
    stale = _decrypted(
        direction_id=direction_id, generation=0, sequence=2, package_id=str(uuid.uuid4())
    )
    result = svc.validate_package(stale)
    assert result.freshness is FreshnessClass.STALE
    assert result.disposition is ValidationDisposition.REJECTED
    conn.close()


def test_future_generation_rejected(tmp_path: Path) -> None:
    conn, session, store = _admin_session(tmp_path)
    direction_id = _inbound_direction(store, conn)
    svc = TransportImportValidationService(conn, session, store=store)
    future = _decrypted(
        direction_id=direction_id, generation=1, sequence=1, package_id=str(uuid.uuid4())
    )
    result = svc.validate_package(future)
    assert result.freshness is FreshnessClass.STALE
    conn.close()


def test_v1_wire_dual_read_as_generation_zero() -> None:
    raw = build_routing_metadata_bytes(
        protocol_version=1,
        generation=0,
        sender_installation_id="s",
        recipient_installation_id="r",
        envelope_key_id=BOOTSTRAP_ENVELOPE_KEY_ID,
        sequence=1,
        package_id="pkg-v1",
        next_wk_key_id="wk-next",
    )
    parsed = parse_routing_metadata_bytes(raw)
    assert parsed.generation == 0
    assert parsed.protocol_version == 1


def test_v2_wire_round_trip_includes_generation() -> None:
    from domain.transport import RoutingMetadata, TransportPackage

    meta = RoutingMetadata(
        protocol_version=2,
        generation=3,
        sender_installation_id="s",
        recipient_installation_id="r",
        envelope_key_id="wk",
        sequence=2,
        package_id="p",
        next_wk_key_id="wk2",
    )
    pkg = TransportPackage(
        routing_metadata=meta,
        signature=b"\x00",
        envelope_ciphertext=b"e",
        payload_ciphertext=b"p",
    )
    wire = serialize_transport_package(pkg)
    decoded = deserialize_transport_package(wire)
    assert decoded.routing_metadata.generation == 3


def test_generation_tamper_breaks_signature_verification(tmp_path: Path) -> None:
    conn, store = _open_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    result = TransportExportService(conn, store=store).export_package(
        direction_id=direction_id, payload=b"x"
    )
    conn.commit()
    meta = result.package.routing_metadata
    tampered_meta = meta.__class__(
        protocol_version=meta.protocol_version,
        generation=meta.generation + 1,
        sender_installation_id=meta.sender_installation_id,
        recipient_installation_id=meta.recipient_installation_id,
        envelope_key_id=meta.envelope_key_id,
        sequence=meta.sequence,
        package_id=meta.package_id,
        next_wk_key_id=meta.next_wk_key_id,
    )
    from domain.transport import TransportPackage

    tampered_pkg = TransportPackage(
        routing_metadata=tampered_meta,
        signature=result.package.signature,
        envelope_ciphertext=result.package.envelope_ciphertext,
        payload_ciphertext=result.package.payload_ciphertext,
    )
    signing_public = conn.execute(
        "SELECT public_key FROM transport_local_signing_keys WHERE key_status='active' LIMIT 1"
    ).fetchone()[0]
    signing_bytes = build_signing_bytes(
        protocol_version=tampered_meta.protocol_version,
        generation=tampered_meta.generation,
        sender_installation_id=tampered_meta.sender_installation_id,
        recipient_installation_id=tampered_meta.recipient_installation_id,
        sequence=tampered_meta.sequence,
        package_id=tampered_meta.package_id,
        envelope_key_id=tampered_meta.envelope_key_id,
        sender_signing_fingerprint=store.get_active_signing_keypair()[0],
        envelope_ciphertext=tampered_pkg.envelope_ciphertext,
        payload_ciphertext=tampered_pkg.payload_ciphertext,
        next_wk_key_id=tampered_meta.next_wk_key_id,
    )
    with pytest.raises(SignatureVerificationError):
        verify_signature(
            public_key=bytes(signing_public),
            message=signing_bytes,
            signature=result.package.signature,
        )


def test_export_continuation_blocked_while_reinit_required(tmp_path: Path) -> None:
    conn, store = _open_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    exporter = TransportExportService(conn, store=store)
    exporter.export_package(direction_id=direction_id, payload=b"one")
    conn.commit()
    store.reinit_direction(direction_id)
    conn.execute(
        "UPDATE transport_direction_state SET accepted_sequence = 1"
        " WHERE id = ?",
        (direction_id,),
    )
    conn.commit()
    with pytest.raises(TransportKeyError, match="reinit"):
        exporter.export_package(direction_id=direction_id, payload=b"should-fail")


def _admin_session(tmp_path: Path):
    from services.bootstrap import BootstrapService

    bootstrap = BootstrapService(clock=lambda: "2026-09-12T00:00:00Z")
    conn, session, _ = bootstrap.initial_administrator_setup(
        login="admin",
        password="AdminPass-1",
        db_path=tmp_path / "epoch.db",
    )
    store = TransportKeyStore(conn, clock=lambda: "2026-09-12T00:00:00Z")
    return conn, session, store


def _inbound_direction(store: TransportKeyStore, conn) -> int:
    local = store.ensure_local_installation()
    store.generate_local_signing_identity()
    store.generate_local_bootstrap_identity()
    signing = generate_signing_keypair()
    bootstrap = generate_bootstrap_keypair()
    peer_id = str(uuid.uuid4())
    trust_id = store.register_peer_trust(
        peer_installation_id=peer_id,
        display_label="Peer",
        signing_public_key=signing.public_key,
        signing_fingerprint=signing.fingerprint,
        bootstrap_public_key=bootstrap.public_key,
        bootstrap_fingerprint=bootstrap.fingerprint,
    )
    direction = store.ensure_direction(
        sender_installation_id=peer_id,
        recipient_installation_id=local.installation_id,
        peer_trust_id=trust_id,
    )
    conn.commit()
    return direction.id
