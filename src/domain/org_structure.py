"""Инварианты оргструктуры: филиал → департамент → отдел (без дублирования данных)."""

from __future__ import annotations

from dataclasses import dataclass


class OrgConsistencyError(ValueError):
    """Несогласованные branch/department/division."""


@dataclass(frozen=True)
class OrgAssignment:
    branch_id: int
    department_id: int | None
    division_id: int | None = None


@dataclass(frozen=True)
class DepartmentRef:
    id: int
    branch_id: int


@dataclass(frozen=True)
class DivisionRef:
    id: int
    branch_id: int
    department_id: int | None


def validate_org_assignment(
    assignment: OrgAssignment,
    department: DepartmentRef | None,
    division: DivisionRef | None = None,
) -> None:
    """
    Проверить согласованность branch/department/division до INSERT.

    department_id сравнивается точно (включая None); division.branch_id
    сверяется с assignment.branch_id напрямую.
    """
    if assignment.department_id is not None:
        if department is None:
            raise OrgConsistencyError("department_id set but department not loaded")
        if department.id != assignment.department_id:
            raise OrgConsistencyError("department id mismatch")
        if department.branch_id != assignment.branch_id:
            raise OrgConsistencyError("department does not belong to branch")
    elif department is not None:
        raise OrgConsistencyError("department provided but assignment has no department_id")

    if assignment.division_id is None:
        if division is not None:
            raise OrgConsistencyError("division provided but assignment has no division_id")
        return

    if division is None:
        raise OrgConsistencyError("division_id set but division not loaded")
    if division.id != assignment.division_id:
        raise OrgConsistencyError("division id mismatch")
    if division.branch_id != assignment.branch_id:
        raise OrgConsistencyError("division does not belong to branch")
    if division.department_id != assignment.department_id:
        raise OrgConsistencyError("division department does not match assignment")


def validate_position_requirements(
    *,
    department_id: int | None,
    division_id: int | None,
    department_required: bool,
    division_required: bool,
) -> None:
    from domain.employee import EmployeeValidationError

    if department_required and department_id is None:
        raise EmployeeValidationError("department is required for this position")
    if division_required and division_id is None:
        raise EmployeeValidationError("division is required for this position")


def validate_position_branch(
    *,
    employee_branch_id: int,
    position_branch_id: int,
) -> None:
    from domain.employee import EmployeeValidationError

    if employee_branch_id != position_branch_id:
        raise EmployeeValidationError("position does not belong to employee's branch")
