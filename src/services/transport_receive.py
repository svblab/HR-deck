"""Inbound transport package crypto receive (EPIC-020 slice 020-C).

Parse → trust/key lookup → verify signature → decrypt envelope → decrypt payload.
Does not write business data, advance inbound transport-state, or apply packages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from data.repositories import UserActionLogRepository
from data.transport_crypto import (
    AeadAuthenticationError,
    SignatureVerificationError,
    aead_open,
    derive_bootstrap_wrap_key,
    verify_signature,
)
from domain.permissions import Permission
from domain.transport import (
    BOOTSTRAP_ENVELOPE_KEY_ID,
    ENTITY_TRANSPORT,
    DirectionStatus,
    TransportEnvelopeDecryptError,
    TransportKeyError,
    TransportPackageMalformedError,
    TransportPayloadDecryptError,
    TransportSignatureError,
    TransportUntrustedSenderError,
    TrustStatus,
    WkRole,
)
from services.authorization import AuthorizationService
from services.session import SessionState
from services.transport_canonical import (
    build_envelope_aad,
    build_payload_aad,
    build_routing_metadata_bytes,
    build_signing_bytes,
    deserialize_transport_package,
)
from services.transport_keys import TransportKeyStore

_WK_USABLE = frozenset({WkRole.ACTIVE, WkRole.HISTORICAL})


@dataclass(frozen=True)
class DecryptedTransportPackage:
    """Crypto-verified package contents (no business apply)."""

    payload: bytes
    sender_installation_id: str
    recipient_installation_id: str
    direction_id: int
    sequence: int
    package_id: str
    envelope_key_id: str
    next_wk_key_id: str
    next_wk_material: bytes


def _split_envelope_plaintext(envelope_plain: bytes) -> tuple[bytes, bytes]:
    if len(envelope_plain) < 8:
        raise TransportEnvelopeDecryptError("envelope plaintext truncated")
    sk_len = int.from_bytes(envelope_plain[:4], "big")
    if 4 + sk_len + 4 > len(envelope_plain):
        raise TransportEnvelopeDecryptError("envelope plaintext truncated")
    sk = envelope_plain[4 : 4 + sk_len]
    offset = 4 + sk_len
    wk_len = int.from_bytes(envelope_plain[offset : offset + 4], "big")
    offset += 4
    if offset + wk_len != len(envelope_plain):
        raise TransportEnvelopeDecryptError("envelope plaintext malformed")
    wk = envelope_plain[offset : offset + wk_len]
    return sk, wk


class TransportReceiveService:
    """Crypto-only receive inside the caller's DB transaction (read-only on success)."""

    def __init__(self, conn, *, store: TransportKeyStore | None = None) -> None:
        self._conn = conn
        self._store = store or TransportKeyStore(conn)

    def receive_package(self, raw_bytes: bytes) -> DecryptedTransportPackage:
        try:
            package = deserialize_transport_package(raw_bytes)
        except ValueError as exc:
            raise TransportPackageMalformedError(str(exc)) from exc

        meta = package.routing_metadata
        try:
            local = self._store.get_local_installation()
        except TransportKeyError as exc:
            raise TransportUntrustedSenderError(str(exc)) from exc
        if meta.recipient_installation_id != local.installation_id:
            raise TransportUntrustedSenderError(
                "package recipient does not match local installation"
            )

        try:
            peer = self._store.get_peer_trust_by_installation_id(meta.sender_installation_id)
        except TransportKeyError as exc:
            raise TransportUntrustedSenderError(str(exc)) from exc
        if peer.signing_trust_status != TrustStatus.ACTIVE:
            raise TransportUntrustedSenderError("peer signing trust is not active")
        if peer.bootstrap_trust_status != TrustStatus.ACTIVE:
            raise TransportUntrustedSenderError("peer bootstrap trust is not active")

        try:
            direction = self._store.get_direction_by_peers(
                sender_installation_id=meta.sender_installation_id,
                recipient_installation_id=meta.recipient_installation_id,
            )
        except TransportKeyError as exc:
            raise TransportUntrustedSenderError(str(exc)) from exc
        if direction.direction_status != DirectionStatus.ACTIVE:
            raise TransportUntrustedSenderError(
                f"direction not receivable: {direction.direction_status}"
            )
        if direction.peer_trust_id != peer.id:
            raise TransportUntrustedSenderError("direction peer trust mismatch")

        routing_bytes = build_routing_metadata_bytes(**asdict(meta))
        signing_bytes = build_signing_bytes(
            protocol_version=meta.protocol_version,
            sender_installation_id=meta.sender_installation_id,
            recipient_installation_id=meta.recipient_installation_id,
            sequence=meta.sequence,
            package_id=meta.package_id,
            envelope_key_id=meta.envelope_key_id,
            sender_signing_fingerprint=peer.signing_key_fingerprint,
            envelope_ciphertext=package.envelope_ciphertext,
            payload_ciphertext=package.payload_ciphertext,
            routing_metadata_bytes=routing_bytes,
        )
        try:
            verify_signature(
                public_key=peer.signing_public_key,
                message=signing_bytes,
                signature=package.signature,
            )
        except SignatureVerificationError as exc:
            raise TransportSignatureError(str(exc)) from exc

        if meta.envelope_key_id == BOOTSTRAP_ENVELOPE_KEY_ID:
            wrap_key = derive_bootstrap_wrap_key(
                local_bootstrap_private_key=self._store.get_active_bootstrap_private_key(),
                peer_bootstrap_public_key=peer.bootstrap_public_key,
                sender_installation_id=meta.sender_installation_id,
                recipient_installation_id=meta.recipient_installation_id,
                package_id=meta.package_id,
            )
        else:
            wk = self._store.lookup_wk_by_key_id(meta.envelope_key_id)
            if wk is None or wk.wk_role not in _WK_USABLE:
                raise TransportEnvelopeDecryptError(
                    f"envelope key_id not usable: {meta.envelope_key_id}"
                )
            if wk.direction_id != direction.id:
                raise TransportEnvelopeDecryptError("envelope key_id direction mismatch")
            wrap_key = wk.wk_key_material

        envelope_aad = build_envelope_aad(
            protocol_version=meta.protocol_version,
            sender_installation_id=meta.sender_installation_id,
            recipient_installation_id=meta.recipient_installation_id,
            sequence=meta.sequence,
            package_id=meta.package_id,
            envelope_key_id=meta.envelope_key_id,
            next_wk_key_id=meta.next_wk_key_id,
        )
        try:
            envelope_plain = aead_open(
                key=wrap_key,
                aad=envelope_aad,
                sealed=package.envelope_ciphertext,
            )
        except AeadAuthenticationError as exc:
            raise TransportEnvelopeDecryptError(str(exc)) from exc

        try:
            sk_material, next_wk_material = _split_envelope_plaintext(envelope_plain)
        except TransportEnvelopeDecryptError:
            raise

        payload_aad = build_payload_aad(
            protocol_version=meta.protocol_version,
            sender_installation_id=meta.sender_installation_id,
            recipient_installation_id=meta.recipient_installation_id,
            sequence=meta.sequence,
            package_id=meta.package_id,
        )
        try:
            payload = aead_open(
                key=sk_material,
                aad=payload_aad,
                sealed=package.payload_ciphertext,
            )
        except AeadAuthenticationError as exc:
            raise TransportPayloadDecryptError(str(exc)) from exc

        return DecryptedTransportPackage(
            payload=payload,
            sender_installation_id=meta.sender_installation_id,
            recipient_installation_id=meta.recipient_installation_id,
            direction_id=direction.id,
            sequence=meta.sequence,
            package_id=meta.package_id,
            envelope_key_id=meta.envelope_key_id,
            next_wk_key_id=meta.next_wk_key_id,
            next_wk_material=next_wk_material,
        )


class TransportReceiveAdminService:
    """Authorized receive facade: IMPORT_EXPORT gate, success audit, commit."""

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
        self._receive = TransportReceiveService(conn, store=store)
        self._audit = UserActionLogRepository(conn)
        self._clock = self._receive._store._clock  # noqa: SLF001

    def _require_import_export(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)

    def receive_package(self, raw_bytes: bytes) -> DecryptedTransportPackage:
        self._require_import_export()
        now = self._clock()
        try:
            result = self._receive.receive_package(raw_bytes)
            self._audit.record(
                account_id=self._session.account_id,
                action_type="transport.package.receive",
                entity_type=ENTITY_TRANSPORT,
                entity_id=result.direction_id,
                result="success",
                details=(
                    f"package_id={result.package_id} sequence={result.sequence}"
                    f" direction_id={result.direction_id}"
                    f" envelope_key_id={result.envelope_key_id}"
                    f" sender_installation_id={result.sender_installation_id}"
                ),
                created_at=now,
            )
            self._conn.commit()
            return result
        except Exception:
            self._conn.rollback()
            raise
