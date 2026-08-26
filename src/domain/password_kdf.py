"""Единые параметры Argon2id для паролей и вывода ключей обёртки (ADR-0004)."""

from __future__ import annotations

import secrets
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type, hash_secret_raw

# --- Единственный источник параметров KDF (не дублировать в вызывающем коде) ---
TIME_COST: Final[int] = 3
MEMORY_COST_KIB: Final[int] = 65_536  # 64 MiB
PARALLELISM: Final[int] = 4
HASH_LEN: Final[int] = 32
SALT_LEN: Final[int] = 16
RECOVERY_CODE_BYTES: Final[int] = 24

_HASHER = PasswordHasher(
    time_cost=TIME_COST,
    memory_cost=MEMORY_COST_KIB,
    parallelism=PARALLELISM,
    hash_len=HASH_LEN,
    salt_len=SALT_LEN,
    type=Type.ID,
)

KDF_ALGORITHM: Final[str] = "argon2id"
KDF_PARAMS: Final[dict[str, int | str]] = {
    "algorithm": KDF_ALGORITHM,
    "time_cost": TIME_COST,
    "memory_cost_kib": MEMORY_COST_KIB,
    "parallelism": PARALLELISM,
    "hash_len": HASH_LEN,
    "salt_len": SALT_LEN,
}


def hash_password(password: str) -> str:
    """Вернуть PHC-строку Argon2id (соль внутри строки)."""
    if not password:
        raise ValueError("password must not be empty")
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Проверить пароль против PHC-хэша. Не логировать пароль."""
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _HASHER.check_needs_rehash(password_hash)


def generate_salt() -> bytes:
    return secrets.token_bytes(SALT_LEN)


def derive_key(secret: str | bytes, salt: bytes, *, length: int = HASH_LEN) -> bytes:
    """Raw Argon2id для AEAD-обёртки мастер-ключа (ADR-0003)."""
    if isinstance(secret, str):
        secret_bytes = secret.encode("utf-8")
    else:
        secret_bytes = secret
    if not secret_bytes:
        raise ValueError("secret must not be empty")
    if len(salt) != SALT_LEN:
        raise ValueError(f"salt must be {SALT_LEN} bytes")
    return hash_secret_raw(
        secret=secret_bytes,
        salt=salt,
        time_cost=TIME_COST,
        memory_cost=MEMORY_COST_KIB,
        parallelism=PARALLELISM,
        hash_len=length,
        type=Type.ID,
    )


def generate_recovery_code() -> str:
    """Криптостойкий одноразовый код (urlsafe); plaintext только для однократного показа."""
    return secrets.token_urlsafe(RECOVERY_CODE_BYTES)
