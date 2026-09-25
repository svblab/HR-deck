"""EPIC-020 020-F: transport replay observation and inbound source cleanup."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from domain.transport import PackageClassification, TransportApplyNotReadyError, WkRole
from services.bootstrap import BootstrapService
from services.transport_import_apply import TransportImportApplyService
from services.transport_import_inbound import (
    TransportInboundImportService,
    best_effort_delete_source,
)
from services.transport_import_replay import TransportImportReplayService
from services.transport_import_validation import (
    FreshnessClass,
    TransportImportValidationService,
    ValidationDisposition,
    ValidationResult,
)
from services.transport_keys import TransportKeyStore
from services.transport_receive import DecryptedTransportPackage

_T0 = "2026-09-25T12:00:00Z"


def _admin_open(tmp_path: Path):
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    store = TransportKeyStore(conn, clock=lambda: _T0)
    return conn, session, store


def _ensure_inbound_direction(store: TransportKeyStore, conn) -> int:
    local = store.ensure_local_installation(display_label="Local")
    store.generate_local_signing_identity()
    store.generate_local_bootstrap_identity()
    peer_installation_id = str(uuid.uuid4())
    peer_id = store.register_peer_trust(
        peer_installation_id=peer_installation_id,
        display_label="Peer",
        signing_public_key=b"\x01" * 32,
        signing_fingerprint="peer-sign-fp",
        bootstrap_public_key=b"\x02" * 32,
        bootstrap_fingerprint="peer-boot-fp",
    )
    direction = store.ensure_direction(
        sender_installation_id=peer_installation_id,
        recipient_installation_id=local.installation_id,
        peer_trust_id=peer_id,
    )
    conn.commit()
    return direction.id


def _decrypted(
    *,
    direction_id: int,
    sequence: int,
    package_id: str,
    tables: dict | None = None,
) -> DecryptedTransportPackage:
    return DecryptedTransportPackage(
        payload=json.dumps(tables or {}).encode("utf-8"),
        sender_installation_id="sender",
        recipient_installation_id="recipient",
        direction_id=direction_id,
        sequence=sequence,
        package_id=package_id,
        envelope_key_id="bootstrap",
        next_wk_key_id=str(uuid.uuid4()),
        next_wk_material=b"\x03" * 32,
    )


def _count_branches(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0])


def test_replay_observe_is_noop_after_apply(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    package_id = str(uuid.uuid4())
    decrypted = _decrypted(direction_id=direction_id, sequence=1, package_id=package_id)
    validation = TransportImportValidationService(conn, session, store=store).validate_package(
        decrypted
    )
    assert validation.disposition is ValidationDisposition.READY_FOR_APPLY

    apply_svc = TransportImportApplyService(conn, session, store=store)
    apply_svc.apply_validated_package(decrypted, validation)
    branches_after_apply = _count_branches(conn)
    wk_after = store.lookup_wk_by_key_id(decrypted.next_wk_key_id)
    assert wk_after is not None
    seq_after = conn.execute(
        "SELECT accepted_sequence FROM transport_direction_state WHERE id = ?",
        (direction_id,),
    ).fetchone()[0]

    replay_validation = TransportImportValidationService(
        conn, session, store=store
    ).validate_package(decrypted)
    assert replay_validation.disposition is ValidationDisposition.REPLAY

    before_seen = conn.execute(
        "SELECT last_seen_at FROM transport_package_records WHERE package_id = ?",
        (package_id,),
    ).fetchone()[0]

    replay_svc = TransportImportReplayService(conn, session, store=store)
    replay_svc.observe_replay(decrypted)
    replay_svc.observe_replay(decrypted)

    assert _count_branches(conn) == branches_after_apply
    assert int(seq_after) == 1
    wk_still = store.lookup_wk_by_key_id(decrypted.next_wk_key_id)
    assert wk_still is not None and wk_still.wk_role is WkRole.ACTIVE

    after_seen = conn.execute(
        "SELECT last_seen_at FROM transport_package_records WHERE package_id = ?",
        (package_id,),
    ).fetchone()[0]
    assert after_seen >= before_seen

    audit = conn.execute(
        "SELECT COUNT(*) FROM user_action_log WHERE action_type = ?",
        ("transport.package.replay",),
    ).fetchone()[0]
    assert int(audit) == 2
    conn.close()


def test_apply_still_rejects_replay_disposition(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    decrypted = _decrypted(
        direction_id=direction_id, sequence=1, package_id=str(uuid.uuid4())
    )
    validation = TransportImportValidationService(conn, session, store=store).validate_package(
        decrypted
    )
    TransportImportApplyService(conn, session, store=store).apply_validated_package(
        decrypted, validation
    )
    replay_validation = TransportImportValidationService(
        conn, session, store=store
    ).validate_package(decrypted)

    with pytest.raises(TransportApplyNotReadyError):
        TransportImportApplyService(conn, session, store=store).apply_validated_package(
            decrypted, replay_validation
        )
    conn.close()


def test_inbound_deletes_source_after_successful_apply(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    package_id = str(uuid.uuid4())
    decrypted = _decrypted(direction_id=direction_id, sequence=1, package_id=package_id)
    validation = TransportImportValidationService(conn, session, store=store).validate_package(
        decrypted
    )
    pkg_file = tmp_path / "inbound.pkg"
    pkg_file.write_bytes(b"wire-bytes")

    inbound = TransportInboundImportService(conn, session, store=store)
    with (
        patch.object(inbound._receive, "receive_package", return_value=decrypted),
        patch.object(inbound._validate, "validate_package", return_value=validation),
    ):
        result = inbound.ingest_bytes(b"wire-bytes", source_path=pkg_file)

    assert result.disposition is ValidationDisposition.READY_FOR_APPLY
    assert result.apply is not None
    assert result.source_deleted is True
    assert not pkg_file.exists()
    conn.close()


def test_inbound_delete_failure_does_not_undo_apply(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    package_id = str(uuid.uuid4())
    decrypted = _decrypted(direction_id=direction_id, sequence=1, package_id=package_id)
    validation = TransportImportValidationService(conn, session, store=store).validate_package(
        decrypted
    )
    pkg_file = tmp_path / "locked.pkg"
    pkg_file.write_bytes(b"wire-bytes")

    inbound = TransportInboundImportService(conn, session, store=store)
    with (
        patch.object(inbound._receive, "receive_package", return_value=decrypted),
        patch.object(inbound._validate, "validate_package", return_value=validation),
        patch(
            "services.transport_import_inbound.best_effort_delete_source",
            return_value=False,
        ),
    ):
        result = inbound.ingest_bytes(b"wire-bytes", source_path=pkg_file)

    assert result.apply is not None
    assert result.source_deleted is False
    assert pkg_file.exists()
    row = conn.execute(
        "SELECT classification FROM transport_package_records WHERE package_id = ?",
        (package_id,),
    ).fetchone()
    assert row is not None and row[0] == PackageClassification.ACCEPTED.value
    conn.close()


def test_inbound_replay_does_not_delete_source(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    package_id = str(uuid.uuid4())
    decrypted = _decrypted(direction_id=direction_id, sequence=1, package_id=package_id)
    ready = TransportImportValidationService(conn, session, store=store).validate_package(
        decrypted
    )
    TransportImportApplyService(conn, session, store=store).apply_validated_package(
        decrypted, ready
    )
    replay_validation = ValidationResult(
        freshness=FreshnessClass.REPLAY,
        disposition=ValidationDisposition.REPLAY,
        directory_plan=None,
        employee_plan=None,
    )
    pkg_file = tmp_path / "replay.pkg"
    pkg_file.write_bytes(b"wire-bytes")

    inbound = TransportInboundImportService(conn, session, store=store)
    with (
        patch.object(inbound._receive, "receive_package", return_value=decrypted),
        patch.object(inbound._validate, "validate_package", return_value=replay_validation),
    ):
        result = inbound.ingest_bytes(b"wire-bytes", source_path=pkg_file)

    assert result.disposition is ValidationDisposition.REPLAY
    assert result.replay is not None
    assert result.source_deleted is False
    assert pkg_file.exists()
    conn.close()


def test_best_effort_delete_source_returns_false_on_error(tmp_path: Path) -> None:
    path = tmp_path / "missing.pkg"
    assert best_effort_delete_source(path) is False
