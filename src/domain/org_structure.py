"""Инварианты оргструктуры: филиал → департамент → отдел (без дублирования данных)."""

from __future__ import annotations

from dataclasses import dataclass


class OrgConsistencyError(ValueError):
    """Несогласованные branch/department/division."""


@dataclass(frozen=True)
class OrgAssignment:
    branch_id: int
    department_id: int
    division_id: int | None = None


@dataclass(frozen=True)
class DepartmentRef:
    id: int
    branch_id: int


@dataclass(frozen=True)
class DivisionRef:
    id: int
    department_id: int


def validate_org_assignment(
    assignment: OrgAssignment,
    department: DepartmentRef,
    division: DivisionRef | None = None,
) -> None:
    """
    Проверить, что department принадлежит branch, а division — department.

    Вызывается из service-слоя до INSERT; дублируется триггерами БД.
    """
    if department.id != assignment.department_id:
        raise OrgConsistencyError("department id mismatch")
    if department.branch_id != assignment.branch_id:
        raise OrgConsistencyError("department does not belong to branch")

    if assignment.division_id is None:
        if division is not None:
            raise OrgConsistencyError("division provided but assignment has no division_id")
        return

    if division is None:
        raise OrgConsistencyError("division_id set but division not loaded")
    if division.id != assignment.division_id:
        raise OrgConsistencyError("division id mismatch")
    if division.department_id != assignment.department_id:
        raise OrgConsistencyError("division does not belong to department")
