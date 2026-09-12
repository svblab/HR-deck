"""TransportCanonicalV1 deterministic encoding (EPIC-019 Phase 0 §3)."""

from __future__ import annotations

MAGIC_SIGNING = b"HRTR\x01"
MAGIC_ROUTING = b"HRTM\x01"
MAGIC_ENVELOPE_AAD = b"HRENV\x01"
MAGIC_PAYLOAD_AAD = b"HRPAY\x01"
BOOTSTRAP_HKDF_INFO_PREFIX = b"HRTR-bootstrap-wrap-v1"


def canon_field_bytes(payload: bytes) -> bytes:
    if len(payload) > 0xFFFFFFFF:
        raise ValueError("field too large")
    return len(payload).to_bytes(4, "big") + payload


def canon_field_utf8(text: str) -> bytes:
    return canon_field_bytes(text.encode("utf-8"))


def canon_field_u32(value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError("u32 out of range")
    return value.to_bytes(4, "big")


def build_routing_metadata_bytes(
    *,
    protocol_version: int,
    sender_installation_id: str,
    recipient_installation_id: str,
    envelope_key_id: str,
    sequence: int,
    package_id: str,
) -> bytes:
    return (
        MAGIC_ROUTING
        + canon_field_u32(protocol_version)
        + canon_field_utf8(sender_installation_id)
        + canon_field_utf8(recipient_installation_id)
        + canon_field_utf8(envelope_key_id)
        + canon_field_u32(sequence)
        + canon_field_utf8(package_id)
    )


def build_signing_bytes(
    *,
    protocol_version: int,
    sender_installation_id: str,
    recipient_installation_id: str,
    sequence: int,
    package_id: str,
    envelope_key_id: str,
    sender_signing_fingerprint: str,
    envelope_ciphertext: bytes,
    payload_ciphertext: bytes,
    routing_metadata_bytes: bytes | None = None,
) -> bytes:
    routing = routing_metadata_bytes or build_routing_metadata_bytes(
        protocol_version=protocol_version,
        sender_installation_id=sender_installation_id,
        recipient_installation_id=recipient_installation_id,
        envelope_key_id=envelope_key_id,
        sequence=sequence,
        package_id=package_id,
    )
    return (
        MAGIC_SIGNING
        + canon_field_u32(protocol_version)
        + canon_field_utf8(sender_installation_id)
        + canon_field_utf8(recipient_installation_id)
        + canon_field_u32(sequence)
        + canon_field_utf8(package_id)
        + canon_field_utf8(envelope_key_id)
        + canon_field_utf8(sender_signing_fingerprint)
        + canon_field_bytes(envelope_ciphertext)
        + canon_field_bytes(payload_ciphertext)
        + canon_field_bytes(routing)
    )


def build_envelope_aad(
    *,
    protocol_version: int,
    sender_installation_id: str,
    recipient_installation_id: str,
    sequence: int,
    package_id: str,
    envelope_key_id: str,
    next_wk_key_id: str,
) -> bytes:
    return (
        MAGIC_ENVELOPE_AAD
        + canon_field_u32(protocol_version)
        + canon_field_utf8(sender_installation_id)
        + canon_field_utf8(recipient_installation_id)
        + canon_field_u32(sequence)
        + canon_field_utf8(package_id)
        + canon_field_utf8(envelope_key_id)
        + canon_field_utf8(next_wk_key_id)
    )


def build_payload_aad(
    *,
    protocol_version: int,
    sender_installation_id: str,
    recipient_installation_id: str,
    sequence: int,
    package_id: str,
) -> bytes:
    return (
        MAGIC_PAYLOAD_AAD
        + canon_field_u32(protocol_version)
        + canon_field_utf8(sender_installation_id)
        + canon_field_utf8(recipient_installation_id)
        + canon_field_u32(sequence)
        + canon_field_utf8(package_id)
    )


def build_bootstrap_hkdf_info(
    *,
    sender_installation_id: str,
    recipient_installation_id: str,
    package_id: str,
) -> bytes:
    return (
        BOOTSTRAP_HKDF_INFO_PREFIX
        + sender_installation_id.encode("utf-8")
        + recipient_installation_id.encode("utf-8")
        + package_id.encode("utf-8")
    )
