"""HR/Administrator transport operator helpers (IMPORT_EXPORT, ADR-0016 / Issue #130).

Read-only direction listing and orchestration of directory-sync export + transport
wire packaging. Does not perform key/trust administration.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from data.db import Connection
from domain.permissions import Permission
from domain.transport import DirectionStatus, TransportKeyError
from services.authorization import AuthorizationService
from services.directory_sync import DirectorySyncService
from services.session import SessionState
from services.transport_export import TransportExportAdminService, TransportExportResult
from services.transport_keys import TransportKeyStore

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class OutboundExportTarget:
    """Outbound direction local installation → peer (exportable with IMPORT_EXPORT)."""

    direction_id: int
    peer_label: str
    direction_status: DirectionStatus
    generation: int
    accepted_sequence: int


@dataclass(frozen=True)
class PersonnelTransportExportResult:
    """Result of a full directory-sync + transport export orchestration."""

    export: TransportExportResult
    tables_exported: tuple[str, ...]
    payload_empty: bool


class TransportOperatorService:
    """Operator-facing transport import/export helpers (not key admin)."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
        store: TransportKeyStore | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._authz = authz or AuthorizationService()
        self._store = store or TransportKeyStore(conn, clock=clock)
        self._clock: Clock = clock if clock is not None else self._store._clock

    def _require_import_export(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)

    def list_outbound_export_targets(self) -> list[OutboundExportTarget]:
        """Outbound directions where this installation is the sender."""
        self._require_import_export()
        try:
            local = self._store.get_local_installation()
        except TransportKeyError:
            return []
        rows = self._conn.execute(
            "SELECT d.id, d.direction_status, d.generation, d.accepted_sequence,"
            " COALESCE(pt.display_label, pt.peer_installation_id)"
            " FROM transport_direction_state d"
            " JOIN transport_peer_trust pt ON pt.id = d.peer_trust_id"
            " WHERE d.sender_installation_id = ?"
            " ORDER BY pt.display_label, d.id",
            (local.installation_id,),
        ).fetchall()
        return [
            OutboundExportTarget(
                direction_id=int(row[0]),
                direction_status=DirectionStatus(str(row[1])),
                generation=int(row[2]),
                accepted_sequence=int(row[3]),
                peer_label=str(row[4]),
            )
            for row in rows
        ]

    def export_personnel_package(self, direction_id: int) -> PersonnelTransportExportResult:
        """Build directory-sync payload, encrypt/sign, optionally bump watermarks."""
        self._require_import_export()
        sync = DirectorySyncService(self._conn, self._session, authz=self._authz)
        pkg = sync.build_export_package(direction_id)
        payload = json.dumps(pkg.tables, ensure_ascii=False, sort_keys=True).encode("utf-8")
        exporter = TransportExportAdminService(
            self._conn, self._session, authz=self._authz, store=self._store
        )
        export_result = exporter.export_package(direction_id=direction_id, payload=payload)
        tables = tuple(pkg.tables.keys())
        if pkg.tables:
            sync.record_export(direction_id, list(tables), exported_at=self._clock())
        return PersonnelTransportExportResult(
            export=export_result,
            tables_exported=tables,
            payload_empty=not pkg.tables,
        )


__all__ = [
    "OutboundExportTarget",
    "PersonnelTransportExportResult",
    "TransportOperatorService",
]
