"""TransportPackage container format (EPIC-020 020-A)."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from domain.transport import RoutingMetadata, TransportPackage
from services.transport_canonical import (
    MAGIC_ENVELOPE_AAD,
    MAGIC_PACKAGE,
    MAGIC_PAYLOAD_AAD,
    MAGIC_ROUTING,
    MAGIC_SIGNING,
    build_routing_metadata_bytes,
    deserialize_transport_package,
    parse_routing_metadata_bytes,
    serialize_transport_package,
)


def _sample_routing_metadata() -> RoutingMetadata:
    return RoutingMetadata(
        protocol_version=1,
        sender_installation_id="sender-install",
        recipient_installation_id="recipient-install",
        envelope_key_id="wk-42",
        sequence=7,
        package_id="pkg-abc",
        next_wk_key_id="wk-next-43",
    )


def _sample_transport_package() -> TransportPackage:
    return TransportPackage(
        routing_metadata=_sample_routing_metadata(),
        signature=b"\xaa\xbb\xcc",
        envelope_ciphertext=b"envelope-bytes",
        payload_ciphertext=b"payload-bytes",
    )


def test_magic_package_distinct_from_other_magics() -> None:
    other_magics = (MAGIC_SIGNING, MAGIC_ROUTING, MAGIC_ENVELOPE_AAD, MAGIC_PAYLOAD_AAD)
    for magic in other_magics:
        assert MAGIC_PACKAGE != magic
        assert not MAGIC_PACKAGE.startswith(magic)
        assert not magic.startswith(MAGIC_PACKAGE)


def test_parse_routing_metadata_bytes_round_trip() -> None:
    metadata = _sample_routing_metadata()
    encoded = build_routing_metadata_bytes(**asdict(metadata))
    parsed = parse_routing_metadata_bytes(encoded)
    assert parsed == metadata


def test_transport_package_round_trip() -> None:
    package = _sample_transport_package()
    encoded = serialize_transport_package(package)
    decoded = deserialize_transport_package(encoded)
    assert decoded == package
    assert encoded.startswith(MAGIC_PACKAGE)


def test_parse_routing_metadata_rejects_bad_magic() -> None:
    data = build_routing_metadata_bytes(
        protocol_version=1,
        sender_installation_id="s",
        recipient_installation_id="r",
        envelope_key_id="k",
        sequence=1,
        package_id="p",
        next_wk_key_id="wk-next",
    ).replace(MAGIC_ROUTING, b"BAD!\x01", 1)
    with pytest.raises(ValueError, match="routing metadata: bad magic"):
        parse_routing_metadata_bytes(data)


def test_parse_routing_metadata_rejects_truncated_bytes() -> None:
    data = build_routing_metadata_bytes(
        protocol_version=1,
        sender_installation_id="s",
        recipient_installation_id="r",
        envelope_key_id="k",
        sequence=1,
        package_id="p",
        next_wk_key_id="wk-next",
    )[:-3]
    with pytest.raises(ValueError, match="routing metadata: truncated"):
        parse_routing_metadata_bytes(data)


def test_parse_routing_metadata_rejects_trailing_garbage() -> None:
    data = (
        build_routing_metadata_bytes(
            protocol_version=1,
            sender_installation_id="s",
            recipient_installation_id="r",
            envelope_key_id="k",
            sequence=1,
            package_id="p",
            next_wk_key_id="wk-next",
        )
        + b"extra"
    )
    with pytest.raises(ValueError, match="routing metadata: trailing garbage"):
        parse_routing_metadata_bytes(data)


def test_deserialize_transport_package_rejects_bad_magic() -> None:
    data = serialize_transport_package(_sample_transport_package()).replace(
        MAGIC_PACKAGE, b"BADP\x01", 1
    )
    with pytest.raises(ValueError, match="transport package: bad magic"):
        deserialize_transport_package(data)


def test_deserialize_transport_package_rejects_wrong_version_byte() -> None:
    data = serialize_transport_package(_sample_transport_package()).replace(
        MAGIC_PACKAGE, b"HRPK\x02", 1
    )
    with pytest.raises(ValueError, match="transport package: bad magic"):
        deserialize_transport_package(data)


def test_deserialize_transport_package_rejects_truncated_bytes() -> None:
    data = serialize_transport_package(_sample_transport_package())[:-2]
    with pytest.raises(ValueError, match="transport package: truncated"):
        deserialize_transport_package(data)


def test_deserialize_transport_package_rejects_trailing_garbage() -> None:
    data = serialize_transport_package(_sample_transport_package()) + b"tail"
    with pytest.raises(ValueError, match="transport package: trailing garbage"):
        deserialize_transport_package(data)
