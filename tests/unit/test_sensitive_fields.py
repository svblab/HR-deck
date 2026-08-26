"""Задел модели чувствительных полей (ANCHOR_CORE §2 / TESTING §2.6)."""

from domain.sensitive import (
    SENSITIVE_EMPLOYEE_COLUMNS,
    Permission,
    SensitiveEmployeeField,
)


def test_sensitive_columns_match_reserved_schema_names() -> None:
    assert SensitiveEmployeeField.HOME_ADDRESS.value == "home_address"
    assert SensitiveEmployeeField.SOCIAL_INSURANCE_NUMBER.value == "social_insurance_number"
    assert SENSITIVE_EMPLOYEE_COLUMNS == {
        "home_address",
        "social_insurance_number",
    }


def test_sensitive_view_permission_is_explicit_not_role_alias() -> None:
    assert Permission.VIEW_SENSITIVE_EMPLOYEE_FIELDS.value == "view_sensitive_employee_fields"
    assert Permission.EDIT_SENSITIVE_EMPLOYEE_FIELDS.value == "edit_sensitive_employee_fields"
