"""KDF паролей: без plaintext, уникальные соли, стабильные параметры."""

from __future__ import annotations

from domain import password_kdf as kdf


def test_kdf_params_documented_in_one_place() -> None:
    assert kdf.KDF_ALGORITHM == "argon2id"
    assert kdf.KDF_PARAMS["time_cost"] == kdf.TIME_COST
    assert kdf.KDF_PARAMS["memory_cost_kib"] == kdf.MEMORY_COST_KIB


def test_hash_and_verify_roundtrip() -> None:
    hashed = kdf.hash_password("correct horse battery")
    assert "correct horse battery" not in hashed
    assert kdf.verify_password(hashed, "correct horse battery")
    assert not kdf.verify_password(hashed, "wrong")


def test_unique_salts() -> None:
    a = kdf.hash_password("same-password")
    b = kdf.hash_password("same-password")
    assert a != b


def test_recovery_code_entropy() -> None:
    code = kdf.generate_recovery_code()
    assert len(code) >= 20
    assert code != kdf.generate_recovery_code()
