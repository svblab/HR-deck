"""TransportCanonicalV1 deterministic encoding (EPIC-019 Phase 0 §3)."""

from __future__ import annotations

from dataclasses import asdict

from domain.transport import RoutingMetadata, TransportPackage

MAGIC_SIGNING = b"HRTR\x01"
MAGIC_ROUTING = b"HRTM\x01"
MAGIC_ENVELOPE_AAD = b"HRENV\x01"
MAGIC_PAYLOAD_AAD = b"HRPAY\x01"
MAGIC_PACKAGE = b"HRPK\x01"
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
    next_wk_key_id: str,
) -> bytes:
    # Deterministic field order (TransportCanonicalV1). ``next_wk_key_id`` is
    # cleartext for recipient envelope-AAD rebuild; authenticity is via the
    # package signature (routing blob) and envelope AEAD AAD binding.
    return (
        MAGIC_ROUTING
        + canon_field_u32(protocol_version)
        + canon_field_utf8(sender_installation_id)
        + canon_field_utf8(recipient_installation_id)
        + canon_field_utf8(envelope_key_id)
        + canon_field_u32(sequence)
        + canon_field_utf8(package_id)
        + canon_field_utf8(next_wk_key_id)
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
    next_wk_key_id: str | None = None,
) -> bytes:
    if routing_metadata_bytes is None:
        if next_wk_key_id is None:
            raise ValueError("next_wk_key_id is required when rebuilding routing bytes")
        routing = build_routing_metadata_bytes(
            protocol_version=protocol_version,
            sender_installation_id=sender_installation_id,
            recipient_installation_id=recipient_installation_id,
            envelope_key_id=envelope_key_id,
            sequence=sequence,
            package_id=package_id,
            next_wk_key_id=next_wk_key_id,
        )
    else:
        routing = routing_metadata_bytes
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


def build_envelope_plaintext(*, sk_material: bytes, next_wk_material: bytes) -> bytes:
    """Canonical cleartext inside a transport envelope (SK_n + WK_{n+1} material)."""
    return canon_field_bytes(sk_material) + canon_field_bytes(next_wk_material)


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


def _parse_canon_field_bytes(data: bytes, offset: int, *, context: str) -> tuple[bytes, int]:
    if offset + 4 > len(data):
        raise ValueError(f"{context}: truncated length prefix")
    length = int.from_bytes(data[offset : offset + 4], "big")
    offset += 4
    if offset + length > len(data):
        raise ValueError(f"{context}: truncated field payload")
    payload = data[offset : offset + length]
    return payload, offset + length


def _parse_canon_field_u32(data: bytes, offset: int, *, context: str) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise ValueError(f"{context}: truncated u32 field")
    value = int.from_bytes(data[offset : offset + 4], "big")
    return value, offset + 4


def _parse_canon_field_utf8(data: bytes, offset: int, *, context: str) -> tuple[str, int]:
    payload, offset = _parse_canon_field_bytes(data, offset, context=context)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{context}: invalid utf-8 field") from exc
    return text, offset


def parse_routing_metadata_bytes(data: bytes) -> RoutingMetadata:
    context = "routing metadata"
    if not data.startswith(MAGIC_ROUTING):
        raise ValueError(f"{context}: bad magic")
    offset = len(MAGIC_ROUTING)
    protocol_version, offset = _parse_canon_field_u32(data, offset, context=context)
    sender_installation_id, offset = _parse_canon_field_utf8(data, offset, context=context)
    recipient_installation_id, offset = _parse_canon_field_utf8(data, offset, context=context)
    envelope_key_id, offset = _parse_canon_field_utf8(data, offset, context=context)
    sequence, offset = _parse_canon_field_u32(data, offset, context=context)
    package_id, offset = _parse_canon_field_utf8(data, offset, context=context)
    next_wk_key_id, offset = _parse_canon_field_utf8(data, offset, context=context)
    if offset != len(data):
        raise ValueError(f"{context}: trailing garbage")
    return RoutingMetadata(
        protocol_version=protocol_version,
        sender_installation_id=sender_installation_id,
        recipient_installation_id=recipient_installation_id,
        envelope_key_id=envelope_key_id,
        sequence=sequence,
        package_id=package_id,
        next_wk_key_id=next_wk_key_id,
    )


def serialize_transport_package(package: TransportPackage) -> bytes:
    routing_bytes = build_routing_metadata_bytes(**asdict(package.routing_metadata))
    return (
        MAGIC_PACKAGE
        + canon_field_bytes(routing_bytes)
        + canon_field_bytes(package.signature)
        + canon_field_bytes(package.envelope_ciphertext)
        + canon_field_bytes(package.payload_ciphertext)
    )


def deserialize_transport_package(data: bytes) -> TransportPackage:
    context = "transport package"
    if not data.startswith(MAGIC_PACKAGE):
        raise ValueError(f"{context}: bad magic")
    offset = len(MAGIC_PACKAGE)
    routing_bytes, offset = _parse_canon_field_bytes(data, offset, context=context)
    signature, offset = _parse_canon_field_bytes(data, offset, context=context)
    envelope_ciphertext, offset = _parse_canon_field_bytes(data, offset, context=context)
    payload_ciphertext, offset = _parse_canon_field_bytes(data, offset, context=context)
    if offset != len(data):
        raise ValueError(f"{context}: trailing garbage")
    routing_metadata = parse_routing_metadata_bytes(routing_bytes)
    return TransportPackage(
        routing_metadata=routing_metadata,
        signature=signature,
        envelope_ciphertext=envelope_ciphertext,
        payload_ciphertext=payload_ciphertext,
    )
