"""Transport crypto key generation (ADR-0007 / EPIC-019)."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from services.transport_canonical import build_bootstrap_hkdf_info

WK_KEY_BYTES = 32
KEY_ID_HEX_BYTES = 16
AEAD_NONCE_BYTES = 12


class AeadAuthenticationError(Exception):
    """AEAD decrypt/verify failed (wrong key, tampered data, or truncated input)."""


class SignatureVerificationError(Exception):
    """Ed25519 signature verification failed."""


@dataclass(frozen=True)
class GeneratedKeypair:
    public_key: bytes
    private_key: bytes
    fingerprint: str


def key_fingerprint(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()


def generate_signing_keypair() -> GeneratedKeypair:
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    public_bytes = public.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    private_bytes = private.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    return GeneratedKeypair(public_bytes, private_bytes, key_fingerprint(public_bytes))


def generate_bootstrap_keypair() -> GeneratedKeypair:
    private = X25519PrivateKey.generate()
    public = private.public_key()
    public_bytes = public.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    private_bytes = private.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    return GeneratedKeypair(public_bytes, private_bytes, key_fingerprint(public_bytes))


def generate_wk_material() -> bytes:
    return secrets.token_bytes(WK_KEY_BYTES)


def generate_wire_key_id() -> str:
    return secrets.token_hex(KEY_ID_HEX_BYTES)


def generate_sk_material() -> bytes:
    return secrets.token_bytes(WK_KEY_BYTES)


def aead_seal(*, key: bytes, aad: bytes, plaintext: bytes) -> bytes:
    nonce = secrets.token_bytes(AEAD_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=aad)
    return nonce + ciphertext


def aead_open(*, key: bytes, aad: bytes, sealed: bytes) -> bytes:
    if len(sealed) < AEAD_NONCE_BYTES:
        raise AeadAuthenticationError("sealed input is truncated")
    nonce = sealed[:AEAD_NONCE_BYTES]
    ciphertext = sealed[AEAD_NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, associated_data=aad)
    except Exception as exc:
        raise AeadAuthenticationError("AEAD authentication failed") from exc


def sign_bytes(*, private_key: bytes, message: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(private_key).sign(message)


def verify_signature(*, public_key: bytes, message: bytes, signature: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, ValueError) as exc:
        raise SignatureVerificationError("signature verification failed") from exc


def derive_bootstrap_wrap_key(
    *,
    local_bootstrap_private_key: bytes,
    peer_bootstrap_public_key: bytes,
    sender_installation_id: str,
    recipient_installation_id: str,
    package_id: str,
) -> bytes:
    private = X25519PrivateKey.from_private_bytes(local_bootstrap_private_key)
    public = X25519PublicKey.from_public_bytes(peer_bootstrap_public_key)
    shared_secret = private.exchange(public)
    info = build_bootstrap_hkdf_info(
        sender_installation_id=sender_installation_id,
        recipient_installation_id=recipient_installation_id,
        package_id=package_id,
    )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=WK_KEY_BYTES,
        salt=None,
        info=info,
    ).derive(shared_secret)
