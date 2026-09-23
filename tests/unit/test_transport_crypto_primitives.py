"""Transport crypto primitives (EPIC-020 prerequisite)."""

from __future__ import annotations

import pytest

from data.transport_crypto import (
    AEAD_NONCE_BYTES,
    WK_KEY_BYTES,
    AeadAuthenticationError,
    SignatureVerificationError,
    aead_open,
    aead_seal,
    derive_bootstrap_wrap_key,
    generate_bootstrap_keypair,
    generate_signing_keypair,
    generate_sk_material,
    sign_bytes,
    verify_signature,
)


def test_aead_seal_open_round_trip() -> None:
    key = b"\x01" * WK_KEY_BYTES
    aad = b"associated-data"
    plaintext = b"secret payload"
    sealed = aead_seal(key=key, aad=aad, plaintext=plaintext)
    assert aead_open(key=key, aad=aad, sealed=sealed) == plaintext


def test_aead_seal_uses_random_nonce() -> None:
    key = b"\x02" * WK_KEY_BYTES
    aad = b"aad"
    plaintext = b"same plaintext"
    first = aead_seal(key=key, aad=aad, plaintext=plaintext)
    second = aead_seal(key=key, aad=aad, plaintext=plaintext)
    assert first != second
    assert first[:AEAD_NONCE_BYTES] != second[:AEAD_NONCE_BYTES]


def test_aead_open_rejects_tampered_ciphertext() -> None:
    key = b"\x03" * WK_KEY_BYTES
    aad = b"aad"
    plaintext = b"payload"
    sealed = bytearray(aead_seal(key=key, aad=aad, plaintext=plaintext))
    sealed[AEAD_NONCE_BYTES] ^= 0x01
    with pytest.raises(AeadAuthenticationError):
        aead_open(key=key, aad=aad, sealed=bytes(sealed))


def test_aead_open_rejects_tampered_tag() -> None:
    key = b"\x04" * WK_KEY_BYTES
    aad = b"aad"
    plaintext = b"payload"
    sealed = bytearray(aead_seal(key=key, aad=aad, plaintext=plaintext))
    sealed[-1] ^= 0x01
    with pytest.raises(AeadAuthenticationError):
        aead_open(key=key, aad=aad, sealed=bytes(sealed))


def test_aead_open_rejects_wrong_aad() -> None:
    key = b"\x05" * WK_KEY_BYTES
    plaintext = b"payload"
    sealed = aead_seal(key=key, aad=b"correct-aad", plaintext=plaintext)
    with pytest.raises(AeadAuthenticationError):
        aead_open(key=key, aad=b"wrong-aad", sealed=sealed)


def test_aead_open_rejects_wrong_key() -> None:
    plaintext = b"payload"
    sealed = aead_seal(key=b"\x06" * WK_KEY_BYTES, aad=b"aad", plaintext=plaintext)
    with pytest.raises(AeadAuthenticationError):
        aead_open(key=b"\x07" * WK_KEY_BYTES, aad=b"aad", sealed=sealed)


def test_aead_open_rejects_truncated_input() -> None:
    key = b"\x08" * WK_KEY_BYTES
    sealed = aead_seal(key=key, aad=b"aad", plaintext=b"payload")
    with pytest.raises(AeadAuthenticationError, match="truncated"):
        aead_open(key=key, aad=b"aad", sealed=sealed[: AEAD_NONCE_BYTES - 1])


def test_sign_verify_round_trip() -> None:
    keypair = generate_signing_keypair()
    message = b"message to sign"
    signature = sign_bytes(private_key=keypair.private_key, message=message)
    verify_signature(
        public_key=keypair.public_key,
        message=message,
        signature=signature,
    )


def test_verify_signature_rejects_wrong_public_key() -> None:
    keypair = generate_signing_keypair()
    other = generate_signing_keypair()
    message = b"message"
    signature = sign_bytes(private_key=keypair.private_key, message=message)
    with pytest.raises(SignatureVerificationError):
        verify_signature(
            public_key=other.public_key,
            message=message,
            signature=signature,
        )


def test_verify_signature_rejects_tampered_message() -> None:
    keypair = generate_signing_keypair()
    message = b"original message"
    signature = sign_bytes(private_key=keypair.private_key, message=message)
    with pytest.raises(SignatureVerificationError):
        verify_signature(
            public_key=keypair.public_key,
            message=b"tampered message",
            signature=signature,
        )


def test_verify_signature_rejects_tampered_signature() -> None:
    keypair = generate_signing_keypair()
    message = b"message"
    signature = bytearray(sign_bytes(private_key=keypair.private_key, message=message))
    signature[0] ^= 0x01
    with pytest.raises(SignatureVerificationError):
        verify_signature(
            public_key=keypair.public_key,
            message=message,
            signature=bytes(signature),
        )


def test_verify_signature_rejects_malformed_signature() -> None:
    keypair = generate_signing_keypair()
    with pytest.raises(SignatureVerificationError):
        verify_signature(
            public_key=keypair.public_key,
            message=b"message",
            signature=b"too-short",
        )


def test_derive_bootstrap_wrap_key_is_symmetric() -> None:
    alice = generate_bootstrap_keypair()
    bob = generate_bootstrap_keypair()
    sender = "sender-install"
    recipient = "recipient-install"
    package_id = "pkg-1"
    alice_to_bob = derive_bootstrap_wrap_key(
        local_bootstrap_private_key=alice.private_key,
        peer_bootstrap_public_key=bob.public_key,
        sender_installation_id=sender,
        recipient_installation_id=recipient,
        package_id=package_id,
    )
    bob_to_alice = derive_bootstrap_wrap_key(
        local_bootstrap_private_key=bob.private_key,
        peer_bootstrap_public_key=alice.public_key,
        sender_installation_id=sender,
        recipient_installation_id=recipient,
        package_id=package_id,
    )
    assert alice_to_bob == bob_to_alice
    assert len(alice_to_bob) == WK_KEY_BYTES


def test_derive_bootstrap_wrap_key_sensitive_to_identity_fields() -> None:
    alice = generate_bootstrap_keypair()
    bob = generate_bootstrap_keypair()
    base = dict(
        local_bootstrap_private_key=alice.private_key,
        peer_bootstrap_public_key=bob.public_key,
        sender_installation_id="sender",
        recipient_installation_id="recipient",
        package_id="pkg-base",
    )
    baseline = derive_bootstrap_wrap_key(**base)
    sender_variant = derive_bootstrap_wrap_key(
        **{**base, "sender_installation_id": "sender-other"},
    )
    recipient_variant = derive_bootstrap_wrap_key(
        **{**base, "recipient_installation_id": "recipient-other"},
    )
    package_variant = derive_bootstrap_wrap_key(
        **{**base, "package_id": "pkg-other"},
    )
    assert sender_variant != baseline
    assert recipient_variant != baseline
    assert package_variant != baseline


def test_generate_sk_material() -> None:
    first = generate_sk_material()
    second = generate_sk_material()
    assert len(first) == WK_KEY_BYTES
    assert len(second) == WK_KEY_BYTES
    assert first != second
