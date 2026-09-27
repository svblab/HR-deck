"""Compose directory-sync payload ↔ transport export/import (harness glue)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from services.transport_import_validation import ValidationDisposition
from tests.e2e_mechanics.peer import Peer

_log = logging.getLogger("e2e_mechanics.transport")


class TransportExchangeHardFail(RuntimeError):
    """Non-automatic import disposition — scenario must stop."""


@dataclass(frozen=True)
class ExchangeResult:
    direction: str
    package_path: Path
    package_id: str
    sequence: int
    disposition: str
    tables_exported: tuple[str, ...]


def export_to_file(sender: Peer, *, exchange_dir: Path, tag: str) -> tuple[Path, object]:
    """Build sync payload, encrypt via transport export, write wire bytes to exchange_dir."""
    assert sender.directions is not None
    assert sender.sync is not None and sender.exporter is not None
    pkg = sender.sync.build_export_package(sender.directions.outbound_id)
    payload = json.dumps(pkg.tables, ensure_ascii=False, sort_keys=True).encode("utf-8")
    result = sender.exporter.export_package(
        direction_id=sender.directions.outbound_id,
        payload=payload,
    )
    if pkg.tables:
        sender.sync.record_export(
            sender.directions.outbound_id,
            list(pkg.tables.keys()),
            exported_at=sender.clock(),
        )
    path = exchange_dir / f"{tag}_{result.package_id}.hrpkg"
    path.write_bytes(result.wire_bytes)
    _log.info(
        "export %s -> file=%s seq=%s tables=%s bytes=%d",
        sender.label,
        path.name,
        result.sequence,
        sorted(pkg.tables.keys()),
        len(result.wire_bytes),
    )
    return path, result


def import_from_file(recipient: Peer, path: Path, *, direction_label: str) -> ExchangeResult:
    """Ingest package; hard-fail on anything other than READY_FOR_APPLY or REPLAY."""
    assert recipient.inbound is not None
    before = recipient.capture_transport_snapshot()
    inbound = recipient.inbound.ingest_from_path(path)
    disposition = inbound.disposition
    if disposition is ValidationDisposition.READY_FOR_APPLY:
        assert inbound.apply is not None
        package_id = inbound.apply.package_id
        sequence = inbound.apply.sequence
    elif disposition is ValidationDisposition.REPLAY:
        assert inbound.replay is not None
        package_id = inbound.replay.package_id
        sequence = -1
        _log.info("import %s replay package_id=%s", recipient.label, package_id)
    else:
        after = recipient.capture_transport_snapshot()
        raise TransportExchangeHardFail(
            f"import {direction_label} on {recipient.label}: disposition={disposition.value}"
            f" reasons={getattr(inbound.validation, 'reject_reasons', ())}"
            f" confirmation={getattr(inbound.validation, 'confirmation_reasons', ())}"
            f" before={before} after={after} path={path}"
        )
    tables: tuple[str, ...] = ()
    if inbound.validation.directory_plan is not None:
        # plans do not expose table names cleanly; leave empty for metrics
        tables = ()
    return ExchangeResult(
        direction=direction_label,
        package_path=path,
        package_id=package_id,
        sequence=sequence,
        disposition=disposition.value,
        tables_exported=tables,
    )


def assert_unchanged_transport_and_business(peer: Peer, before: dict) -> None:
    after = peer.capture_transport_snapshot()
    if after != before:
        raise AssertionError(
            f"{peer.label}: state changed after rejected import\n"
            f"before={before}\nafter={after}"
        )
