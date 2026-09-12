"""Admin facade for TransportKeyStore (authz, audit, commit)."""

from __future__ import annotations

from collections.abc import Callable

from data.repositories import UserActionLogRepository
from domain.permissions import Permission
from domain.transport import ENTITY_TRANSPORT
from services.authorization import AuthorizationService
from services.session import SessionState
from services.transport_keys import Clock, TransportKeyStore


class TransportKeyAdminService:
    """Admin-only facade: authz + audit + commit for standalone key operations."""

    def __init__(
        self,
        conn,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._authz = authz or AuthorizationService()
        self._store = TransportKeyStore(conn, clock=clock)
        self._audit = UserActionLogRepository(conn)
        self._clock = self._store._clock  # noqa: SLF001 — shared clock in tests

    def _require_admin(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.MANAGE_ENCRYPTION_KEYS)

    def _mutate(
        self,
        *,
        action: str,
        entity_id: int | None,
        details: str,
        fn: Callable[[], int],
    ) -> int:
        self._require_admin()
        now = self._clock()
        try:
            result = fn()
            self._audit.record(
                account_id=self._session.account_id,
                action_type=action,
                entity_type=ENTITY_TRANSPORT,
                entity_id=entity_id or result,
                result="success",
                details=details,
                created_at=now,
            )
            self._conn.commit()
            return result
        except Exception:
            self._conn.rollback()
            raise

    def bootstrap_local_identities(self) -> tuple[str, str]:
        result: list[str] = []

        def run() -> int:
            self._store.ensure_local_installation()
            result.append(self._store.generate_local_signing_identity())
            result.append(self._store.generate_local_bootstrap_identity())
            return self._session.account_id

        self._mutate(
            action="transport.identity.bootstrap",
            entity_id=self._session.account_id,
            details="local signing and bootstrap identities created",
            fn=run,
        )
        return result[0], result[1]

    def register_peer(
        self,
        *,
        peer_installation_id: str,
        display_label: str | None,
        signing_public_key: bytes,
        signing_fingerprint: str,
        bootstrap_public_key: bytes,
        bootstrap_fingerprint: str,
    ) -> int:
        return self._mutate(
            action="transport.peer.register",
            entity_id=None,
            details=f"peer={peer_installation_id}",
            fn=lambda: self._store.register_peer_trust(
                peer_installation_id=peer_installation_id,
                display_label=display_label,
                signing_public_key=signing_public_key,
                signing_fingerprint=signing_fingerprint,
                bootstrap_public_key=bootstrap_public_key,
                bootstrap_fingerprint=bootstrap_fingerprint,
            ),
        )
