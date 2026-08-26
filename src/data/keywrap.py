"""Sidecar AEAD-обёртка мастер-ключа SQLCipher (ADR-0003)."""

from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from domain.password_kdf import (
    KDF_ALGORITHM,
    KDF_PARAMS,
    derive_key,
    generate_salt,
)

KEYWRAP_VERSION = 1
WrapKind = Literal["account", "recovery"]


class KeywrapError(Exception):
    """Ошибка чтения/записи/расшифровки sidecar keywrap."""


@dataclass(frozen=True)
class WrapEntry:
    kind: WrapKind
    salt: bytes
    nonce: bytes
    ciphertext: bytes
    login: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "salt_b64": _b64(self.salt),
            "nonce_b64": _b64(self.nonce),
            "ciphertext_b64": _b64(self.ciphertext),
        }
        if self.kind == "account":
            payload["login"] = self.login
        return payload

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> WrapEntry:
        kind = data["kind"]
        if kind not in ("account", "recovery"):
            raise KeywrapError(f"unknown wrap kind: {kind}")
        login = data.get("login") if kind == "account" else None
        if kind == "account" and not login:
            raise KeywrapError("account wrap requires login")
        return cls(
            kind=kind,  # type: ignore[arg-type]
            salt=_unb64(data["salt_b64"]),
            nonce=_unb64(data["nonce_b64"]),
            ciphertext=_unb64(data["ciphertext_b64"]),
            login=str(login) if login is not None else None,
        )


@dataclass
class KeywrapFile:
    wraps: list[WrapEntry]

    def to_json(self) -> dict[str, Any]:
        return {
            "version": KEYWRAP_VERSION,
            "kdf": KDF_ALGORITHM,
            "kdf_params": dict(KDF_PARAMS),
            "wraps": [w.to_json() for w in self.wraps],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> KeywrapFile:
        if int(data.get("version", 0)) != KEYWRAP_VERSION:
            raise KeywrapError(f"unsupported keywrap version: {data.get('version')}")
        wraps = [WrapEntry.from_json(item) for item in data.get("wraps", [])]
        return cls(wraps=wraps)


def keywrap_path_for(db_path: Path | str) -> Path:
    path = Path(db_path)
    return path.with_suffix(path.suffix + ".keywrap")


def wrap_secret(
    master_key: bytes,
    secret: str,
    *,
    kind: WrapKind,
    login: str | None = None,
) -> WrapEntry:
    if kind == "account" and not login:
        raise KeywrapError("account wrap requires login")
    salt = generate_salt()
    kek = derive_key(secret, salt)
    nonce = secrets.token_bytes(12)
    aes = AESGCM(kek)
    ciphertext = aes.encrypt(nonce, master_key, associated_data=_aad(kind, login))
    return WrapEntry(kind=kind, salt=salt, nonce=nonce, ciphertext=ciphertext, login=login)


def unwrap_secret(entry: WrapEntry, secret: str) -> bytes:
    kek = derive_key(secret, entry.salt)
    aes = AESGCM(kek)
    try:
        aad = _aad(entry.kind, entry.login)
        return aes.decrypt(entry.nonce, entry.ciphertext, associated_data=aad)
    except Exception as exc:  # noqa: BLE001 — cryptography raises InvalidTag
        raise KeywrapError("unwrap failed") from exc


def save_keywrap(path: Path | str, keywrap: KeywrapFile) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(keywrap.to_json(), indent=2, ensure_ascii=False) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)


def load_keywrap(path: Path | str) -> KeywrapFile:
    target = Path(path)
    if not target.is_file():
        raise KeywrapError(f"keywrap not found: {target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KeywrapError(f"cannot read keywrap: {target}") from exc
    return KeywrapFile.from_json(data)


def find_account_wrap(keywrap: KeywrapFile, login: str) -> WrapEntry | None:
    for entry in keywrap.wraps:
        if entry.kind == "account" and entry.login == login:
            return entry
    return None


def find_recovery_wrap(keywrap: KeywrapFile) -> WrapEntry | None:
    for entry in keywrap.wraps:
        if entry.kind == "recovery":
            return entry
    return None


def upsert_account_wrap(keywrap: KeywrapFile, entry: WrapEntry) -> KeywrapFile:
    if entry.kind != "account" or not entry.login:
        raise KeywrapError("upsert_account_wrap requires account entry with login")
    remaining = [
        w for w in keywrap.wraps if not (w.kind == "account" and w.login == entry.login)
    ]
    remaining.append(entry)
    return KeywrapFile(wraps=remaining)


def replace_recovery_wrap(keywrap: KeywrapFile, entry: WrapEntry) -> KeywrapFile:
    if entry.kind != "recovery":
        raise KeywrapError("replace_recovery_wrap requires recovery entry")
    remaining = [w for w in keywrap.wraps if w.kind != "recovery"]
    remaining.append(entry)
    return KeywrapFile(wraps=remaining)


def remove_account_wrap(keywrap: KeywrapFile, login: str) -> KeywrapFile:
    return KeywrapFile(
        wraps=[w for w in keywrap.wraps if not (w.kind == "account" and w.login == login)]
    )


def _aad(kind: WrapKind, login: str | None) -> bytes:
    if kind == "account":
        return f"account:{login}".encode()
    return b"recovery"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))
