"""Параметры и таблица стандартных отчётов (ТЗ §3.8.1)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReportKind(StrEnum):
    SNAPSHOT = "snapshot"
    ABSENTEES = "absentees"
    TEMPORARY = "temporary"
    HISTORY = "history"
    CLARIFICATION = "clarification"


class ReportParam(StrEnum):
    PERIOD = "period"
    BRANCH = "branch"
    DEPARTMENT = "department"
    DIVISION = "division"
    STATUS = "status"
    EMPLOYMENT_TYPE = "employment_type"
    EMPLOYEE = "employee"
    GROUP_BY = "group_by"


class ReportGroupBy(StrEnum):
    BRANCH = "branch"
    DEPARTMENT = "department"


@dataclass(frozen=True)
class ReportParams:
    date_from: str | None = None
    date_to: str | None = None
    branch_id: int | None = None
    department_id: int | None = None
    division_id: int | None = None
    status_id: int | None = None
    employment_type_id: int | None = None
    employee_id: int | None = None
    group_by: ReportGroupBy = ReportGroupBy.BRANCH


@dataclass(frozen=True)
class ReportSpec:
    kind: ReportKind
    title: str
    params: frozenset[ReportParam]


@dataclass(frozen=True)
class ReportRow:
    cells: tuple[str, ...]
    group_label: str = ""


@dataclass(frozen=True)
class ReportTable:
    title: str
    columns: tuple[str, ...]
    rows: tuple[ReportRow, ...]


SNAPSHOT_COLUMNS = ("ФИО", "Должность", "Статус", "Начало", "Окончание")
ABSENTEE_COLUMNS = ("ФИО", "Должность", "Статус", "Начало", "Окончание")
TEMPORARY_COLUMNS = ("ФИО", "Должность", "Филиал", "Статус")
HISTORY_COLUMNS = ("Статус", "Начало", "Окончание")
CLARIFICATION_COLUMNS = ("ФИО", "Последний статус", "Окончание")

REPORT_SPECS: dict[ReportKind, ReportSpec] = {
    ReportKind.SNAPSHOT: ReportSpec(
        ReportKind.SNAPSHOT,
        "Сводка «сейчас»",
        frozenset(
            {
                ReportParam.BRANCH,
                ReportParam.DEPARTMENT,
                ReportParam.DIVISION,
                ReportParam.STATUS,
                ReportParam.EMPLOYMENT_TYPE,
                ReportParam.GROUP_BY,
            }
        ),
    ),
    ReportKind.ABSENTEES: ReportSpec(
        ReportKind.ABSENTEES,
        "Отсутствующие за период",
        frozenset(
            {
                ReportParam.PERIOD,
                ReportParam.BRANCH,
                ReportParam.DEPARTMENT,
                ReportParam.DIVISION,
                ReportParam.STATUS,
                ReportParam.EMPLOYMENT_TYPE,
            }
        ),
    ),
    ReportKind.TEMPORARY: ReportSpec(
        ReportKind.TEMPORARY,
        "Временный персонал",
        frozenset(
            {
                ReportParam.BRANCH,
                ReportParam.DEPARTMENT,
                ReportParam.DIVISION,
                ReportParam.STATUS,
            }
        ),
    ),
    ReportKind.HISTORY: ReportSpec(
        ReportKind.HISTORY,
        "История по сотруднику",
        frozenset({ReportParam.EMPLOYEE, ReportParam.PERIOD}),
    ),
    ReportKind.CLARIFICATION: ReportSpec(
        ReportKind.CLARIFICATION,
        "Требуют уточнения",
        frozenset(
            {
                ReportParam.BRANCH,
                ReportParam.DEPARTMENT,
                ReportParam.DIVISION,
                ReportParam.EMPLOYMENT_TYPE,
                ReportParam.GROUP_BY,
            }
        ),
    ),
}

ABSENCE_STATUS_CODES = frozenset({"trip", "sick", "vacation", "day_off", "inactive"})
TEMPORARY_EMPLOYMENT_CODE = "temporary"


def spec_for(kind: ReportKind) -> ReportSpec:
    return REPORT_SPECS[kind]


def uses_param(kind: ReportKind, param: ReportParam) -> bool:
    return param in REPORT_SPECS[kind].params
