"""Transport crypto key generation (ADR-0007 / EPIC-019)."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

WK_KEY_BYTES = 32
KEY_ID_HEX_BYTES = 16


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
