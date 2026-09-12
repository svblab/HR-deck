"""TransportCanonicalV1 golden vectors (ADR-0007 authenticated coverage)."""

from __future__ import annotations

import pytest

from services.transport_canonical import (
    build_envelope_aad,
    build_payload_aad,
    build_routing_metadata_bytes,
    build_signing_bytes,
    canon_field_u32,
    canon_field_utf8,
)


def test_canon_field_u32_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        canon_field_u32(-1)
    with pytest.raises(ValueError):
        canon_field_u32(2**32)


def test_routing_metadata_is_deterministic() -> None:
    kwargs = dict(
        protocol_version=1,
        sender_installation_id="aaa",
        recipient_installation_id="bbb",
        envelope_key_id="wk-1",
        sequence=2,
        package_id="pkg-1",
    )
    first = build_routing_metadata_bytes(**kwargs)
    second = build_routing_metadata_bytes(**kwargs)
    assert first == second
    assert first.startswith(b"HRTM\x01")


def test_signing_bytes_include_routing_and_ciphertexts() -> None:
    routing = build_routing_metadata_bytes(
        protocol_version=1,
        sender_installation_id="sender",
        recipient_installation_id="recipient",
        envelope_key_id="kid-1",
        sequence=1,
        package_id="pkg",
    )
    signing = build_signing_bytes(
        protocol_version=1,
        sender_installation_id="sender",
        recipient_installation_id="recipient",
        sequence=1,
        package_id="pkg",
        envelope_key_id="kid-1",
        sender_signing_fingerprint="fp-sign",
        envelope_ciphertext=b"env",
        payload_ciphertext=b"pay",
        routing_metadata_bytes=routing,
    )
    assert signing.startswith(b"HRTR\x01")
    assert b"env" in signing
    assert b"pay" in signing
    assert routing in signing


def test_envelope_aad_changes_with_next_wk_key_id() -> None:
    base = dict(
        protocol_version=1,
        sender_installation_id="s",
        recipient_installation_id="r",
        sequence=3,
        package_id="p",
        envelope_key_id="wk-old",
    )
    a = build_envelope_aad(**base, next_wk_key_id="wk-next-a")
    b = build_envelope_aad(**base, next_wk_key_id="wk-next-b")
    assert a != b


def test_payload_aad_unique_per_sequence() -> None:
    common = dict(
        protocol_version=1,
        sender_installation_id="s",
        recipient_installation_id="r",
        package_id="p",
    )
    a = build_payload_aad(**common, sequence=1)
    b = build_payload_aad(**common, sequence=2)
    assert a != b
    assert a.startswith(b"HRPAY\x01")


def test_canon_field_utf8_is_stable_across_calls() -> None:
    assert canon_field_utf8("тест") == canon_field_utf8("тест")
