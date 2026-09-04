"""Доменные модели карточки сотрудника (ТЗ §3.1)."""

from __future__ import annotations

from dataclasses import dataclass

from domain.org_structure import (
    DepartmentRef,
    DivisionRef,
    OrgAssignment,
    OrgConsistencyError,
    validate_org_assignment,
)


class EmployeeValidationError(ValueError):
    """Некорректные данные карточки сотрудника."""


@dataclass(frozen=True)
class EmployeeCreateInput:
    full_name: str
    position_id: int
    branch_id: int
    department_id: int
    employment_type_id: int
    division_id: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class EmployeeUpdateInput:
    full_name: str
    position_id: int
    branch_id: int
    department_id: int
    employment_type_id: int
    division_id: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class SensitiveEmployeeInput:
    home_address: str | None = None
    social_insurance_number: str | None = None


@dataclass(frozen=True)
class EmployeeCard:
    """Публичное представление карточки для сервисного слоя."""

    id: int
    full_name: str
    position_id: int
    branch_id: int
    department_id: int
    division_id: int | None
    employment_type_id: int
    note: str | None
    home_address: str | None
    social_insurance_number: str | None
    sensitive_fields_masked: bool
    is_archived: bool


@dataclass(frozen=True)
class EmployeeSearchHit:
    """Результат поиска: различение однофамильцев по подразделению/должности/дате."""

    id: int
    full_name: str
    position_name: str
    branch_name: str
    department_name: str
    division_name: str | None
    hire_date: str | None


def format_search_hit_label(hit: EmployeeSearchHit) -> str:
    """Подпись однофамильца: должность / подразделение / дата приёма (ТЗ §3.1)."""
    parts = [hit.full_name, hit.position_name]
    subdiv = " / ".join(p for p in (hit.department_name, hit.division_name) if p)
    if subdiv:
        parts.append(subdiv)
    elif hit.branch_name:
        parts.append(hit.branch_name)
    if hit.hire_date:
        parts.append(hit.hire_date)
    return " · ".join(p for p in parts if p)


def clean_full_name(full_name: str) -> str:
    clean = full_name.strip()
    if not clean:
        raise EmployeeValidationError("full_name must not be empty")
    return clean


def normalize_name_for_match(value: str) -> str:
    """Сравнение/поиск ФИО: без регистра; «ё» и «е» — один символ (ТЗ §3.4 / §3.7)."""
    return value.strip().casefold().replace("ё", "е")


def validate_employee_org(
    *,
    branch_id: int,
    department_id: int,
    division_id: int | None,
    department: DepartmentRef,
    division: DivisionRef | None,
) -> None:
    assignment = OrgAssignment(
        branch_id=branch_id,
        department_id=department_id,
        division_id=division_id,
    )
    try:
        validate_org_assignment(assignment, department, division)
    except OrgConsistencyError as exc:
        raise EmployeeValidationError(str(exc)) from exc
