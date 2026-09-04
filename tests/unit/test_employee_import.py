"""Unit: разбор и валидация строк импорта (ТЗ §3.7)."""

from __future__ import annotations

import pytest

from domain.employee import EmployeeValidationError, normalize_name_for_match
from domain.employee_import import (
    ImportCatalog,
    evaluate_row,
    parse_hire_date,
)

_CATALOG = ImportCatalog(
    positions={"инженер": 1},
    branches={"филиал север": 2},
    departments={(2, "департамент qa"): 3},
    divisions={(3, "отдел a"): 4},
    employment_types={"штатный": 1, "staff": 1},
)


def _values(**overrides: str) -> dict[str, str]:
    data = {
        "full_name": "Новиков Николай",
        "position": "Инженер",
        "branch": "Филиал Север",
        "department": "Департамент QA",
        "division": "Отдел A",
        "employment_type": "Штатный",
    }
    data.update(overrides)
    return data


def test_evaluate_valid_row_resolves_directory_ids() -> None:
    payload, issues = evaluate_row(_values(), 2, _CATALOG)
    assert not issues
    assert payload is not None
    assert payload.full_name == "Новиков Николай"
    assert payload.position_id == 1
    assert payload.branch_id == 2
    assert payload.department_id == 3
    assert payload.division_id == 4
    assert payload.employment_type_id == 1


def test_evaluate_missing_required_field() -> None:
    payload, issues = evaluate_row(_values(full_name=""), 3, _CATALOG)
    assert payload is None
    assert any("full_name is required" in i.message and i.blocking for i in issues)


def test_evaluate_unknown_directory() -> None:
    payload, issues = evaluate_row(_values(branch="Нет такого"), 4, _CATALOG)
    assert payload is None
    assert any("unknown branch" in i.message for i in issues)


def test_evaluate_malformed_hire_date() -> None:
    payload, issues = evaluate_row(_values(hire_date="32.13.2020"), 5, _CATALOG)
    assert payload is None
    assert any("YYYY-MM-DD" in i.message for i in issues)


def test_parse_hire_date_accepts_iso() -> None:
    assert parse_hire_date("2024-01-15") == "2024-01-15"
    assert parse_hire_date("  ") is None
    with pytest.raises(EmployeeValidationError):
        parse_hire_date("15/01/2024")


def test_normalize_name_treats_yo_and_ye_as_equivalent() -> None:
    """ТЗ §3.7 / ANCHOR_CORE: ФИО не уникальный ID, но совпадение по имени
    при дедупе импорта должно считать «ё» и «е» одним символом (как §3.4 поиск).
    """
    assert normalize_name_for_match("Семёнов") == normalize_name_for_match("Семенов")
    assert normalize_name_for_match("семенов") == normalize_name_for_match("СЕМЁНОВ")


def test_normalize_name_yo_ye_is_case_insensitive() -> None:
    """ТЗ §3.7: нормализация ФИО для сопоставления — без учёта регистра."""
    assert normalize_name_for_match("СЁМЁН") == normalize_name_for_match("семен")
