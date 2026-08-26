"""Имена полей повышенной чувствительности (EPIC-005 UI; права — EPIC-003)."""

from __future__ import annotations

from enum import StrEnum

from domain.permissions import Permission

__all__ = [
    "Permission",
    "SENSITIVE_EMPLOYEE_COLUMNS",
    "SensitiveEmployeeField",
]


class SensitiveEmployeeField(StrEnum):
    """Резервные поля карточки с отдельным разрешением на полный просмотр (ТЗ §3.1)."""

    HOME_ADDRESS = "home_address"
    SOCIAL_INSURANCE_NUMBER = "social_insurance_number"


SENSITIVE_EMPLOYEE_COLUMNS: frozenset[str] = frozenset(f.value for f in SensitiveEmployeeField)

SENSITIVE_MASK = "••••••"


def mask_sensitive_value(value: str | None) -> str | None:
    """Маскированное отображение по умолчанию (ТЗ §3.1 / ANCHOR_CORE §2)."""
    if value is None or value == "":
        return None
    return SENSITIVE_MASK
