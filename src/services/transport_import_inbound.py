"""EPIC-020 slice 020-F: inbound orchestration (validate branch + post-apply cleanup)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from data.db import Connection
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.session import SessionState
from services.transport_import_apply import ApplyResult, TransportImportApplyService
from services.transport_import_replay import ReplayObserveResult, TransportImportReplayService
from services.transport_import_validation import (
    TransportImportValidationService,
    ValidationDisposition,
    ValidationResult,
)
from services.transport_keys import TransportKeyStore
from services.transport_receive import DecryptedTransportPackage, TransportReceiveService

Clock = Callable[[], str]
_log = logging.getLogger(__name__)


def best_effort_delete_source(path: Path) -> bool:
    """Delete inbound package file after a successful apply; never raises."""
    try:
        path.unlink()
        return True
    except OSError as exc:
        _log.warning("failed to delete transport source file %s: %s", path, exc)
        return False


@dataclass(frozen=True)
class InboundImportResult:
    disposition: ValidationDisposition
    validation: ValidationResult
    apply: ApplyResult | None = None
    replay: ReplayObserveResult | None = None
    source_path: Path | None = None
    source_deleted: bool = False


class TransportInboundImportService:
    """Branch on validation disposition: apply, replay observe, or no-op."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        store: TransportKeyStore | None = None,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._store = store or TransportKeyStore(conn, clock=clock)
        self._authz = authz or AuthorizationService()
        self._receive = TransportReceiveService(conn, store=self._store)
        self._validate = TransportImportValidationService(
            conn, session, store=self._store, authz=self._authz
        )
        self._apply = TransportImportApplyService(
            conn, session, store=self._store, authz=self._authz, clock=clock
        )
        self._replay = TransportImportReplayService(
            conn, session, store=self._store, authz=self._authz, clock=clock
        )

    def ingest_bytes(
        self, raw: bytes, *, source_path: Path | None = None
    ) -> InboundImportResult:
        self._require_import_export()
        decrypted = self._receive.receive_package(raw)
        validation = self._validate.validate_package(decrypted)
        return self._dispatch(decrypted, validation, source_path=source_path)

    def ingest_from_path(self, path: Path) -> InboundImportResult:
        return self.ingest_bytes(path.read_bytes(), source_path=path)

    def _dispatch(
        self,
        decrypted: DecryptedTransportPackage,
        validation: ValidationResult,
        *,
        source_path: Path | None,
    ) -> InboundImportResult:
        if validation.disposition is ValidationDisposition.READY_FOR_APPLY:
            apply_result = self._apply.apply_validated_package(decrypted, validation)
            deleted = False
            if source_path is not None:
                deleted = best_effort_delete_source(source_path)
            return InboundImportResult(
                disposition=validation.disposition,
                validation=validation,
                apply=apply_result,
                source_path=source_path,
                source_deleted=deleted,
            )

        if validation.disposition is ValidationDisposition.REPLAY:
            replay_result = self._replay.observe_replay(decrypted)
            return InboundImportResult(
                disposition=validation.disposition,
                validation=validation,
                replay=replay_result,
                source_path=source_path,
                source_deleted=False,
            )

        return InboundImportResult(
            disposition=validation.disposition,
            validation=validation,
            source_path=source_path,
            source_deleted=False,
        )

    def _require_import_export(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)


__all__ = [
    "InboundImportResult",
    "TransportInboundImportService",
    "best_effort_delete_source",
]
