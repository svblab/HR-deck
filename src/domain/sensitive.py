"""Имена полей повышенной чувствительности и задел прав на просмотр (EPIC-005/003)."""

from __future__ import annotations

from enum import StrEnum


class SensitiveEmployeeField(StrEnum):
    """Резервные поля карточки с отдельным разрешением на полный просмотр (ТЗ §3.1)."""

    HOME_ADDRESS = "home_address"
    SOCIAL_INSURANCE_NUMBER = "social_insurance_number"


class Permission(StrEnum):
    """
    Точечные разрешения сверх роли.

    VIEW_SENSITIVE_EMPLOYEE_FIELDS не выдаётся автоматически роли «Сотрудник HR»
    (ANCHOR_CORE §2) — закладывается сейчас, активация UI позже.
    """

    VIEW_SENSITIVE_EMPLOYEE_FIELDS = "view_sensitive_employee_fields"
    EDIT_SENSITIVE_EMPLOYEE_FIELDS = "edit_sensitive_employee_fields"


SENSITIVE_EMPLOYEE_COLUMNS: frozenset[str] = frozenset(f.value for f in SensitiveEmployeeField)
