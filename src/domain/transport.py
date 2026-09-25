"""TransportKeyStore domain types (ADR-0007 / EPIC-019)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

ENTITY_TRANSPORT = "transport"
TRANSPORT_PROTOCOL_VERSION = 1
# Cleartext routing envelope_key_id when the envelope uses bootstrap wrap (package #1).
BOOTSTRAP_ENVELOPE_KEY_ID = "bootstrap"


class TransportKeyError(Exception):
    """Ошибка TransportKeyStore (ключ, направление, replay)."""


class TransportReceiveError(Exception):
    """Base error for crypto-only transport receive (EPIC-020-C)."""


class TransportPackageMalformedError(TransportReceiveError):
    """Wire bytes could not be parsed as a TransportPackage."""


class TransportUntrustedSenderError(TransportReceiveError):
    """Sender installation is unknown or peer trust is not usable."""


class TransportEnvelopeDecryptError(TransportReceiveError):
    """Envelope AEAD decrypt/authenticate failed."""


class TransportSignatureError(TransportReceiveError):
    """Package signature verification failed."""


class TransportPayloadDecryptError(TransportReceiveError):
    """Payload AEAD decrypt/authenticate failed."""


class TransportApplyError(Exception):
    """Base error for atomic transport apply (EPIC-020-E)."""


class TransportApplyNotReadyError(TransportApplyError):
    """Validated package is not READY_FOR_APPLY or failed pre-apply guards."""


class WkRole(StrEnum):
    ACTIVE = "active"
    HISTORICAL = "historical"
    REVOKED = "revoked"
    COMPROMISED = "compromised"
    LOST = "lost"


class PackageClassification(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REPLAY_OBSERVED = "replay_observed"
    PENDING = "pending"


class TrustStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    COMPROMISED = "compromised"


class LocalKeyStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    LOST = "lost"
    COMPROMISED = "compromised"


class DirectionStatus(StrEnum):
    ACTIVE = "active"
    BROKEN = "broken"
    REINIT_REQUIRED = "reinit_required"


@dataclass(frozen=True)
class LocalInstallation:
    installation_id: str
    display_label: str | None


@dataclass(frozen=True)
class WkKeyRecord:
    id: int
    key_id: str
    direction_id: int
    sequence_established: int | None
    wk_key_material: bytes
    wk_role: WkRole
    predecessor_key_id: str | None


@dataclass(frozen=True)
class DirectionState:
    id: int
    sender_installation_id: str
    recipient_installation_id: str
    peer_trust_id: int
    accepted_sequence: int
    current_wk_id: int | None
    direction_status: DirectionStatus


@dataclass(frozen=True)
class PeerTrustRecord:
    id: int
    peer_installation_id: str
    display_label: str | None
    signing_public_key: bytes
    signing_key_fingerprint: str
    signing_trust_status: TrustStatus
    bootstrap_public_key: bytes
    bootstrap_key_fingerprint: str
    bootstrap_trust_status: TrustStatus


@dataclass(frozen=True)
class PackageRecord:
    id: int
    direction_id: int
    package_id: str
    sequence: int
    classification: PackageClassification
    envelope_key_id: str | None


@dataclass(frozen=True)
class RoutingMetadata:
    """Untrusted cleartext routing until signature + envelope AEAD succeed.

    ``next_wk_key_id`` duplicates the authenticated envelope-AAD field so a
    recipient can rebuild AAD for ``aead_open`` (ADR-0007: cleartext may
    duplicate authenticated fields for lookup).
    """

    protocol_version: int
    sender_installation_id: str
    recipient_installation_id: str
    envelope_key_id: str
    sequence: int
    package_id: str
    next_wk_key_id: str


@dataclass(frozen=True)
class TransportPackage:
    routing_metadata: RoutingMetadata
    signature: bytes
    envelope_ciphertext: bytes
    payload_ciphertext: bytes
