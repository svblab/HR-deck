"""Unit: карточка сотрудника и маскирование."""

from __future__ import annotations

import pytest

from domain.employee import (
    EmployeeSearchHit,
    EmployeeValidationError,
    clean_full_name,
    format_search_hit_label,
    validate_employee_org,
)
from domain.org_structure import DepartmentRef, DivisionRef
from domain.sensitive import mask_sensitive_value


def test_clean_full_name_strips_and_rejects_blank() -> None:
    assert clean_full_name("  Иванов  ") == "Иванов"
    with pytest.raises(EmployeeValidationError):
        clean_full_name("  ")


def test_validate_org_assignment_accepts_valid_cascade() -> None:
    validate_employee_org(
        branch_id=1,
        department_id=10,
        division_id=100,
        department=DepartmentRef(id=10, branch_id=1),
        division=DivisionRef(id=100, department_id=10),
    )


def test_validate_org_rejects_division_mismatch() -> None:
    with pytest.raises(EmployeeValidationError):
        validate_employee_org(
            branch_id=1,
            department_id=10,
            division_id=100,
            department=DepartmentRef(id=10, branch_id=1),
            division=DivisionRef(id=100, department_id=99),
        )


def test_mask_sensitive_value() -> None:
    assert mask_sensitive_value(None) is None
    assert mask_sensitive_value("") is None
    masked = mask_sensitive_value("secret")
    assert masked is not None
    assert "secret" not in masked


def test_format_search_hit_label_disambiguates_same_name() -> None:
    hit = EmployeeSearchHit(
        id=1,
        full_name="Иванов Иван Иванович",
        position_name="Инженер",
        branch_name="Филиал Север (тест)",
        department_name="Департамент разработки",
        division_name="Отдел платформы",
        hire_date="2024-01-15",
    )
    label = format_search_hit_label(hit)
    assert "Иванов Иван Иванович" in label
    assert "Инженер" in label
    assert "Отдел платформы" in label
    assert "2024-01-15" in label
