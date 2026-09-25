"""EPIC-020 020-E: atomic transport import apply orchestrator."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from data.directories import BranchRepository
from domain.transport import PackageClassification, TransportApplyNotReadyError, WkRole
from services.bootstrap import BootstrapService
from services.transport_import_validation import FreshnessClass
from services.transport_import_apply import TransportImportApplyService
from services.transport_import_validation import (
    TransportImportValidationService,
    ValidationDisposition,
    ValidationResult,
)
from services.transport_keys import TransportKeyStore
from services.transport_receive import DecryptedTransportPackage

_T0 = "2026-09-25T12:00:00Z"


def _admin_open(tmp_path: Path, *, name: str = "app.db"):
    db = tmp_path / name
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
    tables: dict[str, list[dict[str, object]]] | None = None,
    next_wk_key_id: str | None = None,
) -> DecryptedTransportPackage:
    body = json.dumps(tables or {}).encode("utf-8")
    return DecryptedTransportPackage(
        payload=body,
        sender_installation_id="sender",
        recipient_installation_id="recipient",
        direction_id=direction_id,
        sequence=sequence,
        package_id=package_id,
        envelope_key_id="bootstrap",
        next_wk_key_id=next_wk_key_id or str(uuid.uuid4()),
        next_wk_material=b"\x03" * 32,
    )


def _validate_ready(
    conn, session, store, decrypted: DecryptedTransportPackage
) -> ValidationResult:
    result = TransportImportValidationService(conn, session, store=store).validate_package(
        decrypted
    )
    assert result.disposition is ValidationDisposition.READY_FOR_APPLY
    return result


def test_apply_happy_path_advances_transport_and_audit(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    next_wk = str(uuid.uuid4())
    package_id = str(uuid.uuid4())
    tables = {
        "branches": [
            {
                "id": 1,
                "external_id": str(uuid.uuid4()),
                "name": "Филиал А",
                "is_archived": False,
                "created_at": _T0,
                "updated_at": _T0,
            }
        ]
    }
    decrypted = _decrypted(
        direction_id=direction_id,
        sequence=1,
        package_id=package_id,
        tables=tables,
        next_wk_key_id=next_wk,
    )
    validation = _validate_ready(conn, session, store, decrypted)

    apply_svc = TransportImportApplyService(conn, session, store=store)
    result = apply_svc.apply_validated_package(decrypted, validation)

    assert result.classification is PackageClassification.ACCEPTED
    assert result.sequence == 1
    assert result.directory_stats is not None and result.directory_stats.creates == 1
    assert BranchRepository(conn).list(active_only=False)

    row = conn.execute(
        "SELECT classification, sequence FROM transport_package_records WHERE package_id = ?",
        (package_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == PackageClassification.ACCEPTED.value
    assert int(row[1]) == 1

    direction = conn.execute(
        "SELECT accepted_sequence, current_wk_id FROM transport_direction_state WHERE id = ?",
        (direction_id,),
    ).fetchone()
    assert int(direction[0]) == 1
    wk = store.lookup_wk_by_key_id(next_wk)
    assert wk is not None
    assert wk.wk_role is WkRole.ACTIVE
    assert int(direction[1]) == wk.id

    audit = conn.execute(
        "SELECT action_type, details FROM user_action_log"
        " WHERE action_type = ? ORDER BY id DESC LIMIT 1",
        ("transport.package.apply",),
    ).fetchone()
    assert audit is not None
    assert package_id in str(audit[1])
    conn.close()


def test_apply_not_ready_disposition_writes_nothing(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    before_branches = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
    validation = ValidationResult(
        freshness=FreshnessClass.NEW,
        disposition=ValidationDisposition.REJECTED,
        directory_plan=None,
        employee_plan=None,
        reject_reasons=("test",),
    )
    decrypted = _decrypted(
        direction_id=direction_id, sequence=1, package_id=str(uuid.uuid4())
    )
    apply_svc = TransportImportApplyService(conn, session, store=store)
    with pytest.raises(TransportApplyNotReadyError):
        apply_svc.apply_validated_package(decrypted, validation)
    after_branches = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
    assert after_branches == before_branches
    assert (
        conn.execute("SELECT COUNT(*) FROM transport_package_records").fetchone()[0] == 0
    )
    conn.close()


def test_apply_replay_after_accepted_rejects(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    package_id = str(uuid.uuid4())
    decrypted = _decrypted(
        direction_id=direction_id,
        sequence=1,
        package_id=package_id,
        tables={},
    )
    validation = _validate_ready(conn, session, store, decrypted)
    apply_svc = TransportImportApplyService(conn, session, store=store)
    apply_svc.apply_validated_package(decrypted, validation)

    with pytest.raises(TransportApplyNotReadyError):
        apply_svc.apply_validated_package(decrypted, validation)
    conn.close()


def test_apply_atomicity_rolls_back_directory_on_employee_fail(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    tables = {
        "branches": [
            {
                "id": 1,
                "external_id": str(uuid.uuid4()),
                "name": "Филиал B",
                "is_archived": False,
                "created_at": _T0,
                "updated_at": _T0,
            }
        ]
    }
    decrypted = _decrypted(
        direction_id=direction_id,
        sequence=1,
        package_id=str(uuid.uuid4()),
        tables=tables,
    )
    validation = _validate_ready(conn, session, store, decrypted)
    apply_svc = TransportImportApplyService(conn, session, store=store)

    def _boom(_plan, *, commit=True):
        raise RuntimeError("forced employee apply failure")

    with patch.object(apply_svc._employees, "apply_employee_plan", side_effect=_boom):
        with pytest.raises(RuntimeError, match="forced employee"):
            apply_svc.apply_validated_package(decrypted, validation)

    assert conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM transport_package_records").fetchone()[0] == 0
    direction = conn.execute(
        "SELECT accepted_sequence FROM transport_direction_state WHERE id = ?",
        (direction_id,),
    ).fetchone()
    assert int(direction[0]) == 0
    conn.close()


def test_apply_directory_plan_uses_commit_false(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    decrypted = _decrypted(
        direction_id=direction_id,
        sequence=1,
        package_id=str(uuid.uuid4()),
        tables={},
    )
    validation = _validate_ready(conn, session, store, decrypted)
    apply_svc = TransportImportApplyService(conn, session, store=store)

    with (
        patch.object(
            apply_svc._directories,
            "apply_directory_plan",
            wraps=apply_svc._directories.apply_directory_plan,
        ) as dir_mock,
        patch.object(
            apply_svc._employees,
            "apply_employee_plan",
            wraps=apply_svc._employees.apply_employee_plan,
        ) as emp_mock,
    ):
        apply_svc.apply_validated_package(decrypted, validation)
        dir_mock.assert_called_once()
        assert dir_mock.call_args.kwargs.get("commit") is False
        emp_mock.assert_called_once()
        assert emp_mock.call_args.kwargs.get("commit") is False
    conn.close()
