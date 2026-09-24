"""Outbound transport package export (EPIC-020 slice 020-B).

Builds signed ``TransportPackage`` wire bytes from opaque caller-supplied payload.
Does not import, validate business data, or commit database transactions.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass

from data.repositories import UserActionLogRepository
from data.transport_crypto import (
    aead_seal,
    derive_bootstrap_wrap_key,
    generate_sk_material,
    sign_bytes,
)
from domain.permissions import Permission
from domain.transport import (
    BOOTSTRAP_ENVELOPE_KEY_ID,
    ENTITY_TRANSPORT,
    TRANSPORT_PROTOCOL_VERSION,
    DirectionStatus,
    RoutingMetadata,
    TransportKeyError,
    TransportPackage,
    TrustStatus,
    WkRole,
)
from services.authorization import AuthorizationService
from services.session import SessionState
from services.transport_canonical import (
    build_envelope_aad,
    build_envelope_plaintext,
    build_payload_aad,
    build_routing_metadata_bytes,
    build_signing_bytes,
    serialize_transport_package,
)
from services.transport_keys import TransportKeyStore


@dataclass(frozen=True)
class TransportExportResult:
    """Result of a single outbound export (in-memory package + wire bytes)."""

    package: TransportPackage
    wire_bytes: bytes
    package_id: str
    sequence: int
    direction_id: int


class TransportExportService:
    """Compose outbound transport packages inside the caller's DB transaction."""

    def __init__(self, conn, *, store: TransportKeyStore | None = None) -> None:
        self._conn = conn
        self._store = store or TransportKeyStore(conn)

    def export_package(
        self,
        *,
        direction_id: int,
        payload: bytes,
    ) -> TransportExportResult:
        """
        Build and persist outbound transport state for one package.

        ``payload`` is opaque application bytes; this service does not interpret it.
        """
        direction = self._store.get_direction(direction_id)
        if direction.direction_status != DirectionStatus.ACTIVE:
            raise TransportKeyError(f"direction not exportable: {direction.direction_status}")

        peer = self._store.get_peer_trust(direction.peer_trust_id)
        if peer.signing_trust_status != TrustStatus.ACTIVE:
            raise TransportKeyError("peer signing trust is not active")
        if peer.bootstrap_trust_status != TrustStatus.ACTIVE:
            raise TransportKeyError("peer bootstrap trust is not active")

        local = self._store.ensure_local_installation()
        if direction.sender_installation_id != local.installation_id:
            raise TransportKeyError("direction sender does not match local installation")
        if direction.recipient_installation_id != peer.peer_installation_id:
            raise TransportKeyError("direction recipient does not match peer trust")

        signing_fingerprint, signing_private = self._store.get_active_signing_keypair()
        sequence = direction.accepted_sequence + 1
        package_id = str(uuid.uuid4())

        sk_material = generate_sk_material()
        current_wk = self._store.get_current_wk(direction_id)
        predecessor_key_id = current_wk.key_id if current_wk is not None else None
        next_wk = self._store.create_wk_key(
            direction_id=direction_id,
            wk_role=WkRole.HISTORICAL,
            predecessor_key_id=predecessor_key_id,
        )

        payload_aad = build_payload_aad(
            protocol_version=TRANSPORT_PROTOCOL_VERSION,
            sender_installation_id=direction.sender_installation_id,
            recipient_installation_id=direction.recipient_installation_id,
            sequence=sequence,
            package_id=package_id,
        )
        payload_ciphertext = aead_seal(
            key=sk_material,
            aad=payload_aad,
            plaintext=payload,
        )

        envelope_plaintext = build_envelope_plaintext(
            sk_material=sk_material,
            next_wk_material=next_wk.wk_key_material,
        )
        if current_wk is None:
            routing_envelope_key_id = BOOTSTRAP_ENVELOPE_KEY_ID
            bootstrap_private = self._store.get_active_bootstrap_private_key()
            wrap_key = derive_bootstrap_wrap_key(
                local_bootstrap_private_key=bootstrap_private,
                peer_bootstrap_public_key=peer.bootstrap_public_key,
                sender_installation_id=direction.sender_installation_id,
                recipient_installation_id=direction.recipient_installation_id,
                package_id=package_id,
            )
        else:
            routing_envelope_key_id = current_wk.key_id
            wrap_key = current_wk.wk_key_material

        envelope_aad = build_envelope_aad(
            protocol_version=TRANSPORT_PROTOCOL_VERSION,
            sender_installation_id=direction.sender_installation_id,
            recipient_installation_id=direction.recipient_installation_id,
            sequence=sequence,
            package_id=package_id,
            envelope_key_id=routing_envelope_key_id,
            next_wk_key_id=next_wk.key_id,
        )
        envelope_ciphertext = aead_seal(
            key=wrap_key,
            aad=envelope_aad,
            plaintext=envelope_plaintext,
        )

        routing_metadata = RoutingMetadata(
            protocol_version=TRANSPORT_PROTOCOL_VERSION,
            sender_installation_id=direction.sender_installation_id,
            recipient_installation_id=direction.recipient_installation_id,
            envelope_key_id=routing_envelope_key_id,
            sequence=sequence,
            package_id=package_id,
        )
        routing_bytes = build_routing_metadata_bytes(**asdict(routing_metadata))
        signing_bytes = build_signing_bytes(
            protocol_version=TRANSPORT_PROTOCOL_VERSION,
            sender_installation_id=direction.sender_installation_id,
            recipient_installation_id=direction.recipient_installation_id,
            sequence=sequence,
            package_id=package_id,
            envelope_key_id=routing_envelope_key_id,
            sender_signing_fingerprint=signing_fingerprint,
            envelope_ciphertext=envelope_ciphertext,
            payload_ciphertext=payload_ciphertext,
            routing_metadata_bytes=routing_bytes,
        )
        signature = sign_bytes(private_key=signing_private, message=signing_bytes)

        package = TransportPackage(
            routing_metadata=routing_metadata,
            signature=signature,
            envelope_ciphertext=envelope_ciphertext,
            payload_ciphertext=payload_ciphertext,
        )
        wire_bytes = serialize_transport_package(package)

        self._store.record_outbound_export(
            direction_id=direction_id,
            package_id=package_id,
            sequence=sequence,
            envelope_key_id=routing_envelope_key_id,
            established_wk=next_wk,
        )

        return TransportExportResult(
            package=package,
            wire_bytes=wire_bytes,
            package_id=package_id,
            sequence=sequence,
            direction_id=direction_id,
        )


class TransportExportAdminService:
    """Authorized export facade: IMPORT_EXPORT gate, audit, and commit.

    Key/trust administration remains on ``TransportKeyAdminService``
    (``Permission.MANAGE_ENCRYPTION_KEYS``). Ordinary package export uses
    ``Permission.IMPORT_EXPORT`` per ADR-0007.
    """

    def __init__(
        self,
        conn,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
        store: TransportKeyStore | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._authz = authz or AuthorizationService()
        self._export = TransportExportService(conn, store=store)
        self._audit = UserActionLogRepository(conn)
        self._clock = self._export._store._clock  # noqa: SLF001

    def _require_export_permission(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)

    def export_package(self, *, direction_id: int, payload: bytes) -> TransportExportResult:
        self._require_export_permission()
        now = self._clock()
        try:
            result = self._export.export_package(direction_id=direction_id, payload=payload)
            meta = result.package.routing_metadata
            self._audit.record(
                account_id=self._session.account_id,
                action_type="transport.package.export",
                entity_type=ENTITY_TRANSPORT,
                entity_id=direction_id,
                result="success",
                details=(
                    f"package_id={result.package_id} sequence={result.sequence}"
                    f" direction_id={direction_id}"
                    f" envelope_key_id={meta.envelope_key_id}"
                    f" recipient_installation_id={meta.recipient_installation_id}"
                ),
                created_at=now,
            )
            self._conn.commit()
            return result
        except Exception:
            self._conn.rollback()
            raise
