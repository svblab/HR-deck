"""Transport outbound export (EPIC-020 slice 020-B)."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from data.transport_crypto import (
    SignatureVerificationError,
    aead_open,
    derive_bootstrap_wrap_key,
    generate_bootstrap_keypair,
    generate_signing_keypair,
    verify_signature,
)
from domain.permissions import RoleCode
from domain.transport import (
    BOOTSTRAP_ENVELOPE_KEY_ID,
    TRANSPORT_PROTOCOL_VERSION,
    PackageClassification,
    TransportKeyError,
)
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.transport_canonical import (
    build_envelope_aad,
    build_payload_aad,
    build_signing_bytes,
    deserialize_transport_package,
)
from services.transport_export import TransportExportAdminService, TransportExportService
from services.transport_keys import TransportKeyStore


def _open_conn(tmp_path: Path):
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    store = TransportKeyStore(conn, clock=lambda: "2026-09-12T00:00:00Z")
    return conn, store


def _bootstrap_direction(store: TransportKeyStore, conn) -> tuple[int, bytes]:
    local = store.ensure_local_installation(display_label="Local")
    store.generate_local_signing_identity()
    store.generate_local_bootstrap_identity()
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
    return direction.id, bootstrap.private_key


def _local_signing_public(conn) -> bytes:
    row = conn.execute(
        "SELECT public_key FROM transport_local_signing_keys WHERE key_status='active' LIMIT 1"
    ).fetchone()
    assert row is not None
    return bytes(row[0])


def _decrypt_export_envelope(
    *,
    package,
    store: TransportKeyStore,
    direction_id: int,
    recipient_bootstrap_private: bytes,
    sender_bootstrap_public: bytes,
    next_wk_key_id: str,
) -> bytes:
    meta = package.routing_metadata
    envelope_aad = build_envelope_aad(
        protocol_version=meta.protocol_version,
        sender_installation_id=meta.sender_installation_id,
        recipient_installation_id=meta.recipient_installation_id,
        sequence=meta.sequence,
        package_id=meta.package_id,
        envelope_key_id=meta.envelope_key_id,
        next_wk_key_id=next_wk_key_id,
    )
    if meta.envelope_key_id == BOOTSTRAP_ENVELOPE_KEY_ID:
        wrap_key = derive_bootstrap_wrap_key(
            local_bootstrap_private_key=recipient_bootstrap_private,
            peer_bootstrap_public_key=sender_bootstrap_public,
            sender_installation_id=meta.sender_installation_id,
            recipient_installation_id=meta.recipient_installation_id,
            package_id=meta.package_id,
        )
    else:
        prior = store.lookup_wk_by_key_id(meta.envelope_key_id)
        assert prior is not None
        wrap_key = prior.wk_key_material
    return aead_open(
        key=wrap_key,
        aad=envelope_aad,
        sealed=package.envelope_ciphertext,
    )


def test_first_export_uses_bootstrap_envelope_and_serializes(tmp_path: Path) -> None:
    conn, store = _open_conn(tmp_path)
    direction_id, recipient_bootstrap_private = _bootstrap_direction(store, conn)
    signing_public = _local_signing_public(conn)
    exporter = TransportExportService(conn, store=store)
    payload = b"opaque-business-bytes"

    result = exporter.export_package(direction_id=direction_id, payload=payload)
    conn.commit()

    assert result.sequence == 1
    assert result.package.routing_metadata.envelope_key_id == BOOTSTRAP_ENVELOPE_KEY_ID
    decoded = deserialize_transport_package(result.wire_bytes)
    assert decoded == result.package

    signing_bytes = build_signing_bytes(
        protocol_version=TRANSPORT_PROTOCOL_VERSION,
        sender_installation_id=decoded.routing_metadata.sender_installation_id,
        recipient_installation_id=decoded.routing_metadata.recipient_installation_id,
        sequence=decoded.routing_metadata.sequence,
        package_id=decoded.routing_metadata.package_id,
        envelope_key_id=decoded.routing_metadata.envelope_key_id,
        sender_signing_fingerprint=store.get_active_signing_keypair()[0],
        envelope_ciphertext=decoded.envelope_ciphertext,
        payload_ciphertext=decoded.payload_ciphertext,
    )
    verify_signature(
        public_key=signing_public,
        message=signing_bytes,
        signature=decoded.signature,
    )

    sender_bootstrap_public = conn.execute(
        "SELECT public_key FROM transport_local_bootstrap_keys WHERE key_status='active' LIMIT 1"
    ).fetchone()[0]
    next_wk_key_id = store.get_current_wk(direction_id).key_id  # type: ignore[union-attr]
    envelope_plain = _decrypt_export_envelope(
        package=decoded,
        store=store,
        direction_id=direction_id,
        recipient_bootstrap_private=recipient_bootstrap_private,
        sender_bootstrap_public=bytes(sender_bootstrap_public),
        next_wk_key_id=next_wk_key_id,
    )
    sk_material, next_wk_material = _split_envelope_plaintext(envelope_plain)
    payload_aad = build_payload_aad(
        protocol_version=TRANSPORT_PROTOCOL_VERSION,
        sender_installation_id=decoded.routing_metadata.sender_installation_id,
        recipient_installation_id=decoded.routing_metadata.recipient_installation_id,
        sequence=decoded.routing_metadata.sequence,
        package_id=decoded.routing_metadata.package_id,
    )
    assert aead_open(key=sk_material, aad=payload_aad, sealed=decoded.payload_ciphertext) == payload
    current = store.get_current_wk(direction_id)
    assert current is not None
    assert current.wk_key_material == next_wk_material

    row = conn.execute(
        "SELECT classification, sequence FROM transport_package_records WHERE package_id = ?",
        (result.package_id,),
    ).fetchone()
    assert row == (PackageClassification.PENDING.value, 1)


def test_second_export_uses_established_wk_chain(tmp_path: Path) -> None:
    conn, store = _open_conn(tmp_path)
    direction_id, recipient_bootstrap_private = _bootstrap_direction(store, conn)
    exporter = TransportExportService(conn, store=store)

    first = exporter.export_package(direction_id=direction_id, payload=b"first")
    conn.commit()
    wk1_key_id = store.get_current_wk(direction_id).key_id  # type: ignore[union-attr]
    second = exporter.export_package(direction_id=direction_id, payload=b"second")
    conn.commit()

    assert first.sequence == 1
    assert second.sequence == 2
    assert second.package.routing_metadata.envelope_key_id == wk1_key_id
    assert second.package.routing_metadata.envelope_key_id != BOOTSTRAP_ENVELOPE_KEY_ID
    sender_bootstrap_public = conn.execute(
        "SELECT public_key FROM transport_local_bootstrap_keys WHERE key_status='active' LIMIT 1"
    ).fetchone()[0]
    envelope_plain = _decrypt_export_envelope(
        package=second.package,
        store=store,
        direction_id=direction_id,
        recipient_bootstrap_private=recipient_bootstrap_private,
        sender_bootstrap_public=bytes(sender_bootstrap_public),
        next_wk_key_id=store.get_current_wk(direction_id).key_id,  # type: ignore[union-attr]
    )
    sk_material, _ = _split_envelope_plaintext(envelope_plain)
    payload_aad = build_payload_aad(
        protocol_version=TRANSPORT_PROTOCOL_VERSION,
        sender_installation_id=second.package.routing_metadata.sender_installation_id,
        recipient_installation_id=second.package.routing_metadata.recipient_installation_id,
        sequence=second.package.routing_metadata.sequence,
        package_id=second.package.routing_metadata.package_id,
    )
    assert (
        aead_open(key=sk_material, aad=payload_aad, sealed=second.package.payload_ciphertext)
        == b"second"
    )


def test_export_generates_fresh_sk_per_package(tmp_path: Path) -> None:
    conn, store = _open_conn(tmp_path)
    direction_id, recipient_bootstrap_private = _bootstrap_direction(store, conn)
    exporter = TransportExportService(conn, store=store)
    sender_bootstrap_public = conn.execute(
        "SELECT public_key FROM transport_local_bootstrap_keys WHERE key_status='active' LIMIT 1"
    ).fetchone()[0]
    first = exporter.export_package(direction_id=direction_id, payload=b"a")
    conn.commit()
    sk_first, _ = _split_envelope_plaintext(
        _decrypt_export_envelope(
            package=first.package,
            store=store,
            direction_id=direction_id,
            recipient_bootstrap_private=recipient_bootstrap_private,
            sender_bootstrap_public=bytes(sender_bootstrap_public),
            next_wk_key_id=store.get_current_wk(direction_id).key_id,  # type: ignore[union-attr]
        )
    )
    second = exporter.export_package(direction_id=direction_id, payload=b"b")
    conn.commit()
    sk_second, _ = _split_envelope_plaintext(
        _decrypt_export_envelope(
            package=second.package,
            store=store,
            direction_id=direction_id,
            recipient_bootstrap_private=recipient_bootstrap_private,
            sender_bootstrap_public=bytes(sender_bootstrap_public),
            next_wk_key_id=store.get_current_wk(direction_id).key_id,  # type: ignore[union-attr]
        )
    )
    assert sk_first != sk_second


def test_export_rejects_mismatched_direction_peer(tmp_path: Path) -> None:
    conn, store = _open_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    other_peer = str(uuid.uuid4())
    conn.execute(
        "UPDATE transport_direction_state SET recipient_installation_id = ? WHERE id = ?",
        (other_peer, direction_id),
    )
    exporter = TransportExportService(conn, store=store)
    with pytest.raises(TransportKeyError, match="recipient does not match"):
        exporter.export_package(direction_id=direction_id, payload=b"x")


def test_tampered_signature_fails_verification(tmp_path: Path) -> None:
    conn, store = _open_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    signing_public = _local_signing_public(conn)
    exporter = TransportExportService(conn, store=store)
    result = exporter.export_package(direction_id=direction_id, payload=b"payload")
    conn.commit()

    tampered = bytearray(result.package.signature)
    tampered[0] ^= 0x01
    signing_bytes = build_signing_bytes(
        protocol_version=TRANSPORT_PROTOCOL_VERSION,
        sender_installation_id=result.package.routing_metadata.sender_installation_id,
        recipient_installation_id=result.package.routing_metadata.recipient_installation_id,
        sequence=result.package.routing_metadata.sequence,
        package_id=result.package.routing_metadata.package_id,
        envelope_key_id=result.package.routing_metadata.envelope_key_id,
        sender_signing_fingerprint=store.get_active_signing_keypair()[0],
        envelope_ciphertext=result.package.envelope_ciphertext,
        payload_ciphertext=result.package.payload_ciphertext,
    )
    with pytest.raises(SignatureVerificationError):
        verify_signature(
            public_key=signing_public,
            message=signing_bytes,
            signature=bytes(tampered),
        )


def _open_admin_conn(tmp_path: Path):
    conn, session, _code = BootstrapService(
        clock=lambda: "2026-09-12T00:00:00Z"
    ).initial_administrator_setup(
        login="admin",
        password="AdminPass-1",
        db_path=tmp_path / "app.db",
    )
    store = TransportKeyStore(conn, clock=lambda: "2026-09-12T00:00:00Z")
    return conn, session, store


def _direction_snapshot(conn, direction_id: int) -> tuple[int, int | None, int, int]:
    row = conn.execute(
        "SELECT accepted_sequence, current_wk_id FROM transport_direction_state WHERE id = ?",
        (direction_id,),
    ).fetchone()
    packages = conn.execute(
        "SELECT COUNT(*) FROM transport_package_records WHERE direction_id = ?",
        (direction_id,),
    ).fetchone()[0]
    wks = conn.execute(
        "SELECT COUNT(*) FROM transport_wk_keys WHERE direction_id = ?",
        (direction_id,),
    ).fetchone()[0]
    return int(row[0]), row[1], int(packages), int(wks)


def test_admin_export_allows_hr_import_export_permission(tmp_path: Path) -> None:
    conn, admin_session, store = _open_admin_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    hr = SessionState(
        account_id=admin_session.account_id,
        login="hr",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin_session.master_key,
        locked=False,
    )
    facade = TransportExportAdminService(conn, hr, store=store)
    result = facade.export_package(direction_id=direction_id, payload=b"hr-payload")
    assert result.sequence == 1
    audit = conn.execute(
        "SELECT action_type, result, details FROM user_action_log"
        " WHERE action_type = 'transport.package.export' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert audit is not None
    assert audit[0] == "transport.package.export"
    assert audit[1] == "success"
    assert f"package_id={result.package_id}" in audit[2]
    assert f"sequence={result.sequence}" in audit[2]
    assert f"direction_id={direction_id}" in audit[2]
    assert "envelope_key_id=" in audit[2]


def test_admin_export_rejects_observer(tmp_path: Path) -> None:
    conn, admin_session, store = _open_admin_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    observer = SessionState(
        account_id=admin_session.account_id,
        login="obs",
        role=RoleCode.OBSERVER,
        master_key=admin_session.master_key,
        locked=False,
    )
    facade = TransportExportAdminService(conn, observer, store=store)
    with pytest.raises(AuthorizationError):
        facade.export_package(direction_id=direction_id, payload=b"x")
    assert _direction_snapshot(conn, direction_id) == (0, None, 0, 0)


def test_failed_export_does_not_advance_transport_state(tmp_path: Path) -> None:
    conn, admin_session, store = _open_admin_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    facade = TransportExportAdminService(conn, admin_session, store=store)
    with (
        patch(
            "services.transport_export.serialize_transport_package",
            side_effect=RuntimeError("serialize boom"),
        ),
        pytest.raises(RuntimeError, match="serialize boom"),
    ):
        facade.export_package(direction_id=direction_id, payload=b"payload")
    assert _direction_snapshot(conn, direction_id) == (0, None, 0, 0)
    audit_count = conn.execute(
        "SELECT COUNT(*) FROM user_action_log WHERE action_type = 'transport.package.export'"
    ).fetchone()[0]
    assert audit_count == 0


def test_failed_persistence_does_not_leave_package_record(tmp_path: Path) -> None:
    conn, admin_session, store = _open_admin_conn(tmp_path)
    direction_id, _ = _bootstrap_direction(store, conn)
    facade = TransportExportAdminService(conn, admin_session, store=store)
    with (
        patch.object(
            store,
            "record_outbound_export",
            side_effect=RuntimeError("persist boom"),
        ),
        pytest.raises(RuntimeError, match="persist boom"),
    ):
        facade.export_package(direction_id=direction_id, payload=b"payload")
    # create_wk_key may insert a HISTORICAL row before persist; rollback must discard it.
    assert _direction_snapshot(conn, direction_id) == (0, None, 0, 0)


def _split_envelope_plaintext(envelope_plain: bytes) -> tuple[bytes, bytes]:
    length = int.from_bytes(envelope_plain[:4], "big")
    sk = envelope_plain[4 : 4 + length]
    offset = 4 + length
    wk_length = int.from_bytes(envelope_plain[offset : offset + 4], "big")
    offset += 4
    wk = envelope_plain[offset : offset + wk_length]
    return sk, wk
