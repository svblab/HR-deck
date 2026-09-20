"""Семантика типов занятости (ADR-0011)."""

from __future__ import annotations

from typing import Protocol

# Зарезервированные system codes из migration 0001 + ADR-0011 seed.
SYSTEM_EMPLOYMENT_TYPE_CODES = frozenset({"staff", "temporary", "contractor", "dismissed"})

# Предпочтительный тип метаданных при архивировании (не display name).
DEFAULT_ARCHIVING_EMPLOYMENT_CODE = "dismissed"


class _ArchivingTypeCandidate(Protocol):
    code: str
    archives_record: bool
    is_archived: bool


def is_system_employment_type_code(code: str) -> bool:
    return code.strip().casefold() in SYSTEM_EMPLOYMENT_TYPE_CODES


def resolve_default_archiving_type(
    types: list[_ArchivingTypeCandidate],
    *,
    active_only: bool = True,
) -> _ArchivingTypeCandidate | None:
    """Выбор типа занятости для метаданных при архивировании (ADR-0011).

    1. Кандидаты: archives_record = 1; при active_only — is_archived = 0.
    2. Предпочтение: code = DEFAULT_ARCHIVING_EMPLOYMENT_CODE ('dismissed').
    3. Иначе: минимальный code в лексикографическом порядке (детерминизм).
    """
    candidates = [
        row
        for row in types
        if row.archives_record and (not active_only or not row.is_archived)
    ]
    if not candidates:
        return None
    for row in candidates:
        if row.code == DEFAULT_ARCHIVING_EMPLOYMENT_CODE:
            return row
    return min(candidates, key=lambda row: row.code)


__all__ = [
    "DEFAULT_ARCHIVING_EMPLOYMENT_CODE",
    "SYSTEM_EMPLOYMENT_TYPE_CODES",
    "is_system_employment_type_code",
    "resolve_default_archiving_type",
]
