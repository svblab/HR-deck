"""Transport inbound crypto receive (EPIC-020 slice 020-C)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from domain.permissions import RoleCode
from domain.transport import (
    BOOTSTRAP_ENVELOPE_KEY_ID,
    TransportEnvelopeDecryptError,
    TransportPackageMalformedError,
    TransportSignatureError,
    TransportUntrustedSenderError,
    WkRole,
)
from services.authorization import AuthorizationError
from services.session import SessionState
from services.transport_canonical import serialize_transport_package
from services.transport_export import TransportExportService
from services.transport_keys import TransportKeyStore
from services.transport_receive import TransportReceiveAdminService, TransportReceiveService


def _open_store(tmp_path: Path, name: str) -> tuple:
    key = generate_master_key()
    conn = create_database(tmp_path / name, key)
    apply_pending_migrations(conn)
    store = TransportKeyStore(conn, clock=lambda: "2026-09-12T00:00:00Z")
    return conn, store


def _snapshot_direction(conn, direction_id: int) -> tuple[int, int | None, int, int]:
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


def _local_publics(conn) -> tuple[bytes, str, bytes, str]:
    signing = conn.execute(
        "SELECT public_key, key_fingerprint FROM transport_local_signing_keys"
        " WHERE key_status='active' LIMIT 1"
    ).fetchone()
    bootstrap = conn.execute(
        "SELECT public_key, key_fingerprint FROM transport_local_bootstrap_keys"
        " WHERE key_status='active' LIMIT 1"
    ).fetchone()
    assert signing is not None and bootstrap is not None
    return bytes(signing[0]), str(signing[1]), bytes(bootstrap[0]), str(bootstrap[1])


def _paired_sender_recipient(tmp_path: Path):
    """Two installations with mutual trust and matching S→R directions."""
    sender_conn, sender_store = _open_store(tmp_path, "sender.db")
    recipient_conn, recipient_store = _open_store(tmp_path, "recipient.db")

    sender_local = sender_store.ensure_local_installation(display_label="Sender")
    sender_store.generate_local_signing_identity()
    sender_store.generate_local_bootstrap_identity()
    s_sign_pub, s_sign_fp, s_boot_pub, s_boot_fp = _local_publics(sender_conn)

    recipient_local = recipient_store.ensure_local_installation(display_label="Recipient")
    recipient_store.generate_local_signing_identity()
    recipient_store.generate_local_bootstrap_identity()
    r_sign_pub, r_sign_fp, r_boot_pub, r_boot_fp = _local_publics(recipient_conn)

    sender_peer = sender_store.register_peer_trust(
        peer_installation_id=recipient_local.installation_id,
        display_label="Recipient",
        signing_public_key=r_sign_pub,
        signing_fingerprint=r_sign_fp,
        bootstrap_public_key=r_boot_pub,
        bootstrap_fingerprint=r_boot_fp,
    )
    recipient_peer = recipient_store.register_peer_trust(
        peer_installation_id=sender_local.installation_id,
        display_label="Sender",
        signing_public_key=s_sign_pub,
        signing_fingerprint=s_sign_fp,
        bootstrap_public_key=s_boot_pub,
        bootstrap_fingerprint=s_boot_fp,
    )

    sender_direction = sender_store.ensure_direction(
        sender_installation_id=sender_local.installation_id,
        recipient_installation_id=recipient_local.installation_id,
        peer_trust_id=sender_peer,
    )
    recipient_direction = recipient_store.ensure_direction(
        sender_installation_id=sender_local.installation_id,
        recipient_installation_id=recipient_local.installation_id,
        peer_trust_id=recipient_peer,
    )
    sender_conn.commit()
    recipient_conn.commit()
    return (
        sender_conn,
        sender_store,
        sender_direction.id,
        recipient_conn,
        recipient_store,
        recipient_direction.id,
    )


def _seed_received_wk(
    store: TransportKeyStore,
    conn,
    *,
    direction_id: int,
    key_id: str,
    material: bytes,
    sequence: int,
) -> None:
    """Simulate 020-E inbound WK establish for subsequent-package tests only."""
    wk = store.create_wk_key(
        direction_id=direction_id,
        wk_role=WkRole.HISTORICAL,
        wk_material=material,
        wire_key_id=key_id,
    )
    store.activate_wk_for_direction(
        direction_id=direction_id,
        wk_row_id=wk.id,
        accepted_sequence=sequence,
    )
    conn.commit()


def test_receive_first_package_round_trip(tmp_path: Path) -> None:
    (
        sender_conn,
        sender_store,
        sender_dir,
        recipient_conn,
        recipient_store,
        recipient_dir,
    ) = _paired_sender_recipient(tmp_path)
    exporter = TransportExportService(sender_conn, store=sender_store)
    receiver = TransportReceiveService(recipient_conn, store=recipient_store)
    before = _snapshot_direction(recipient_conn, recipient_dir)

    exported = exporter.export_package(direction_id=sender_dir, payload=b"opaque-bytes")
    sender_conn.commit()

    result = receiver.receive_package(exported.wire_bytes)
    assert result.payload == b"opaque-bytes"
    assert result.sequence == 1
    assert result.package_id == exported.package_id
    assert result.envelope_key_id == BOOTSTRAP_ENVELOPE_KEY_ID
    assert result.next_wk_key_id == exported.package.routing_metadata.next_wk_key_id
    assert result.direction_id == recipient_dir
    assert _snapshot_direction(recipient_conn, recipient_dir) == before


def test_receive_subsequent_package_uses_wk_chain(tmp_path: Path) -> None:
    (
        sender_conn,
        sender_store,
        sender_dir,
        recipient_conn,
        recipient_store,
        recipient_dir,
    ) = _paired_sender_recipient(tmp_path)
    exporter = TransportExportService(sender_conn, store=sender_store)
    receiver = TransportReceiveService(recipient_conn, store=recipient_store)

    first = exporter.export_package(direction_id=sender_dir, payload=b"first")
    sender_conn.commit()
    first_recv = receiver.receive_package(first.wire_bytes)
    _seed_received_wk(
        recipient_store,
        recipient_conn,
        direction_id=recipient_dir,
        key_id=first_recv.next_wk_key_id,
        material=first_recv.next_wk_material,
        sequence=first_recv.sequence,
    )

    second = exporter.export_package(direction_id=sender_dir, payload=b"second")
    sender_conn.commit()
    before = _snapshot_direction(recipient_conn, recipient_dir)
    second_recv = receiver.receive_package(second.wire_bytes)

    assert second_recv.payload == b"second"
    assert second_recv.sequence == 2
    assert second_recv.envelope_key_id == first_recv.next_wk_key_id
    assert second_recv.envelope_key_id != BOOTSTRAP_ENVELOPE_KEY_ID
    assert _snapshot_direction(recipient_conn, recipient_dir) == before


def test_receive_rejects_tampered_signature(tmp_path: Path) -> None:
    (
        sender_conn,
        sender_store,
        sender_dir,
        recipient_conn,
        recipient_store,
        recipient_dir,
    ) = _paired_sender_recipient(tmp_path)
    exported = TransportExportService(sender_conn, store=sender_store).export_package(
        direction_id=sender_dir, payload=b"x"
    )
    sender_conn.commit()
    sig = bytearray(exported.package.signature)
    sig[0] ^= 0x01
    wire = serialize_transport_package(replace(exported.package, signature=bytes(sig)))
    before = _snapshot_direction(recipient_conn, recipient_dir)
    with pytest.raises(TransportSignatureError):
        TransportReceiveService(recipient_conn, store=recipient_store).receive_package(wire)
    assert _snapshot_direction(recipient_conn, recipient_dir) == before


def test_receive_rejects_tampered_ciphertext(tmp_path: Path) -> None:
    (
        sender_conn,
        sender_store,
        sender_dir,
        recipient_conn,
        recipient_store,
        recipient_dir,
    ) = _paired_sender_recipient(tmp_path)
    exported = TransportExportService(sender_conn, store=sender_store).export_package(
        direction_id=sender_dir, payload=b"payload"
    )
    sender_conn.commit()
    ct = bytearray(exported.package.payload_ciphertext)
    ct[0] ^= 0x01
    wire = serialize_transport_package(
        replace(exported.package, payload_ciphertext=bytes(ct))
    )
    before = _snapshot_direction(recipient_conn, recipient_dir)
    # Signature covers ciphertext; tamper fails authentication before payload open.
    with pytest.raises(TransportSignatureError):
        TransportReceiveService(recipient_conn, store=recipient_store).receive_package(wire)
    assert _snapshot_direction(recipient_conn, recipient_dir) == before


def test_receive_rejects_unknown_sender(tmp_path: Path) -> None:
    (
        sender_conn,
        sender_store,
        sender_dir,
        recipient_conn,
        recipient_store,
        _recipient_dir,
    ) = _paired_sender_recipient(tmp_path)
    exported = TransportExportService(sender_conn, store=sender_store).export_package(
        direction_id=sender_dir, payload=b"x"
    )
    sender_conn.commit()
    recipient_conn.execute("DELETE FROM transport_direction_state")
    recipient_conn.execute("DELETE FROM transport_peer_trust")
    recipient_conn.commit()
    with pytest.raises(TransportUntrustedSenderError):
        TransportReceiveService(recipient_conn, store=recipient_store).receive_package(
            exported.wire_bytes
        )


def test_receive_rejects_wrong_recipient_installation(tmp_path: Path) -> None:
    (
        sender_conn,
        sender_store,
        sender_dir,
        _recipient_conn,
        _recipient_store,
        _recipient_dir,
    ) = _paired_sender_recipient(tmp_path)
    exported = TransportExportService(sender_conn, store=sender_store).export_package(
        direction_id=sender_dir, payload=b"x"
    )
    sender_conn.commit()
    before = _snapshot_direction(sender_conn, sender_dir)
    with pytest.raises(TransportUntrustedSenderError, match="recipient does not match"):
        TransportReceiveService(sender_conn, store=sender_store).receive_package(
            exported.wire_bytes
        )
    assert _snapshot_direction(sender_conn, sender_dir) == before


def test_receive_rejects_missing_wk_for_subsequent(tmp_path: Path) -> None:
    (
        sender_conn,
        sender_store,
        sender_dir,
        recipient_conn,
        recipient_store,
        recipient_dir,
    ) = _paired_sender_recipient(tmp_path)
    exporter = TransportExportService(sender_conn, store=sender_store)
    exporter.export_package(direction_id=sender_dir, payload=b"first")
    sender_conn.commit()
    second = exporter.export_package(direction_id=sender_dir, payload=b"second")
    sender_conn.commit()
    before = _snapshot_direction(recipient_conn, recipient_dir)
    with pytest.raises(TransportEnvelopeDecryptError):
        TransportReceiveService(recipient_conn, store=recipient_store).receive_package(
            second.wire_bytes
        )
    assert _snapshot_direction(recipient_conn, recipient_dir) == before


def test_receive_rejects_malformed_bytes(tmp_path: Path) -> None:
    _sc, _ss, _sd, recipient_conn, recipient_store, recipient_dir = _paired_sender_recipient(
        tmp_path
    )
    before = _snapshot_direction(recipient_conn, recipient_dir)
    with pytest.raises(TransportPackageMalformedError):
        TransportReceiveService(recipient_conn, store=recipient_store).receive_package(b"nope")
    assert _snapshot_direction(recipient_conn, recipient_dir) == before


def test_receive_admin_allows_hr_and_writes_audit(tmp_path: Path) -> None:
    from services.bootstrap import BootstrapService

    sender_conn, sender_store = _open_store(tmp_path, "sender.db")
    sender_local = sender_store.ensure_local_installation(display_label="Sender")
    sender_store.generate_local_signing_identity()
    sender_store.generate_local_bootstrap_identity()
    s_sign_pub, s_sign_fp, s_boot_pub, s_boot_fp = _local_publics(sender_conn)

    recipient_conn, admin_session, _code = BootstrapService(
        clock=lambda: "2026-09-12T00:00:00Z"
    ).initial_administrator_setup(
        login="admin",
        password="AdminPass-1",
        db_path=tmp_path / "recipient.db",
    )
    recipient_store = TransportKeyStore(
        recipient_conn, clock=lambda: "2026-09-12T00:00:00Z"
    )
    recipient_local = recipient_store.ensure_local_installation(display_label="Recipient")
    recipient_store.generate_local_signing_identity()
    recipient_store.generate_local_bootstrap_identity()
    r_sign_pub, r_sign_fp, r_boot_pub, r_boot_fp = _local_publics(recipient_conn)

    sender_peer = sender_store.register_peer_trust(
        peer_installation_id=recipient_local.installation_id,
        display_label="Recipient",
        signing_public_key=r_sign_pub,
        signing_fingerprint=r_sign_fp,
        bootstrap_public_key=r_boot_pub,
        bootstrap_fingerprint=r_boot_fp,
    )
    recipient_peer = recipient_store.register_peer_trust(
        peer_installation_id=sender_local.installation_id,
        display_label="Sender",
        signing_public_key=s_sign_pub,
        signing_fingerprint=s_sign_fp,
        bootstrap_public_key=s_boot_pub,
        bootstrap_fingerprint=s_boot_fp,
    )
    sender_dir = sender_store.ensure_direction(
        sender_installation_id=sender_local.installation_id,
        recipient_installation_id=recipient_local.installation_id,
        peer_trust_id=sender_peer,
    ).id
    recipient_dir = recipient_store.ensure_direction(
        sender_installation_id=sender_local.installation_id,
        recipient_installation_id=recipient_local.installation_id,
        peer_trust_id=recipient_peer,
    ).id
    sender_conn.commit()
    recipient_conn.commit()

    exported = TransportExportService(sender_conn, store=sender_store).export_package(
        direction_id=sender_dir, payload=b"hr"
    )
    sender_conn.commit()

    hr = SessionState(
        account_id=admin_session.account_id,
        login="hr",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin_session.master_key,
        locked=False,
    )
    before = _snapshot_direction(recipient_conn, recipient_dir)
    facade = TransportReceiveAdminService(recipient_conn, hr, store=recipient_store)
    result = facade.receive_package(exported.wire_bytes)
    assert result.payload == b"hr"
    assert _snapshot_direction(recipient_conn, recipient_dir) == before
    audit = recipient_conn.execute(
        "SELECT action_type, result, details FROM user_action_log"
        " WHERE action_type = 'transport.package.receive' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert audit is not None
    assert audit[0] == "transport.package.receive"
    assert audit[1] == "success"
    assert f"package_id={result.package_id}" in audit[2]


def test_receive_admin_rejects_observer(tmp_path: Path) -> None:
    (
        sender_conn,
        sender_store,
        sender_dir,
        recipient_conn,
        recipient_store,
        recipient_dir,
    ) = _paired_sender_recipient(tmp_path)
    exported = TransportExportService(sender_conn, store=sender_store).export_package(
        direction_id=sender_dir, payload=b"x"
    )
    sender_conn.commit()
    observer = SessionState(
        account_id=1,
        login="obs",
        role=RoleCode.OBSERVER,
        master_key=generate_master_key(),
        locked=False,
    )
    before = _snapshot_direction(recipient_conn, recipient_dir)
    with pytest.raises(AuthorizationError):
        TransportReceiveAdminService(
            recipient_conn, observer, store=recipient_store
        ).receive_package(exported.wire_bytes)
    assert _snapshot_direction(recipient_conn, recipient_dir) == before
