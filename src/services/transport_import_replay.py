"""EPIC-020 slice 020-F: idempotent replay observation for accepted transport packages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from data.db import Connection
from data.repositories import UserActionLogRepository
from domain.permissions import Permission
from domain.transport import ENTITY_TRANSPORT, TransportKeyError
from services.authorization import AuthorizationService
from services.session import SessionState
from services.transport_keys import TransportKeyStore
from services.transport_receive import DecryptedTransportPackage

Clock = Callable[[], str]


@dataclass(frozen=True)
class ReplayObserveResult:
    package_id: str
    direction_id: int
    sequence: int
    package_record_id: int


class TransportImportReplayService:
    """Touch ACCEPTED package replays without business or transport-state writes."""

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
        self._clock = self._store._clock  # noqa: SLF001
        self._audit = UserActionLogRepository(conn)

    def observe_replay(self, decrypted: DecryptedTransportPackage) -> ReplayObserveResult:
        """Record replay observation (last_seen_at + audit); idempotent."""
        self._require_import_export()
        now = self._clock()
        repo = self._store._repo  # noqa: SLF001
        existing = repo.find_package(decrypted.package_id)
        if existing is None:
            raise TransportKeyError(
                f"package not accepted for replay: {decrypted.package_id}"
            )

        try:
            repo.touch_package_replay(decrypted.package_id, now=now)
            self._audit.record(
                account_id=self._session.account_id,
                action_type="transport.package.replay",
                entity_type=ENTITY_TRANSPORT,
                entity_id=decrypted.direction_id,
                result="success",
                details=(
                    f"package_id={decrypted.package_id} sequence={decrypted.sequence}"
                    f" direction_id={decrypted.direction_id}"
                ),
                created_at=now,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return ReplayObserveResult(
            package_id=decrypted.package_id,
            direction_id=decrypted.direction_id,
            sequence=decrypted.sequence,
            package_record_id=existing.id,
        )

    def _require_import_export(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)


__all__ = ["ReplayObserveResult", "TransportImportReplayService"]
