"""Агрегация данных для отчёта «Сводка по филиалу» (шаблоны Excel, ADR-0005)."""

from __future__ import annotations

from domain.reports import ABSENCE_STATUS_CODES
from domain.roster import RosterRow, format_display_date

LIST_STATUS_CODES = frozenset({"vacation", "sick", "trip"})


def division_group_label(row: RosterRow) -> str:
    """Ключ группировки строки: отдел (division), иначе департамент."""
    if row.division_name:
        return row.division_name
    if row.department_name:
        return row.department_name
    return "Без отдела"


def is_absent_status(status_code: str | None) -> bool:
    """Отсутствие по существующей бизнес-логике стандартных отчётов."""
    return status_code in ABSENCE_STATUS_CODES


def join_employee_names(names: list[str]) -> str:
    """Список ФИО через «; » в порядке сортировки."""
    return "; ".join(sorted(names))


def build_branch_summary_rows(
    rows: list[RosterRow],
    status_codes: dict[int, str],
) -> tuple[list[dict[str, str]], int, int]:
    """
    Сгруппировать сотрудников филиала по отделу и подготовить row_records.

    Возвращает (row_records, branch_total, branch_absent).
    """
    groups: dict[str, list[tuple[RosterRow, str | None]]] = {}
    for row in rows:
        key = division_group_label(row)
        code = status_codes.get(row.status_id) if row.status_id is not None else None
        groups.setdefault(key, []).append((row, code))

    row_records: list[dict[str, str]] = []
    branch_total = 0
    branch_absent = 0

    for division_name in sorted(groups.keys()):
        members = groups[division_name]
        total = len(members)
        absent = sum(1 for _, code in members if is_absent_status(code))
        vacation: list[str] = []
        sick: list[str] = []
        trip: list[str] = []
        for member, code in sorted(members, key=lambda item: item[0].full_name):
            if code == "vacation":
                vacation.append(member.full_name)
            elif code == "sick":
                sick.append(member.full_name)
            elif code == "trip":
                trip.append(member.full_name)

        branch_total += total
        branch_absent += absent
        row_records.append(
            {
                "employee.division": division_name,
                "report.department_total": str(total),
                "report.department_absent": str(absent),
                "report.vacation_employees": join_employee_names(vacation),
                "report.sick_leave_employees": join_employee_names(sick),
                "report.business_trip_employees": join_employee_names(trip),
            }
        )

    return row_records, branch_total, branch_absent


def build_branch_summary_context(
    rows: list[RosterRow],
    status_codes: dict[int, str],
    *,
    branch_name: str,
    as_of: str,
    title: str = "Сводка по филиалу",
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Скаляры и row_records для generate_excel_report."""
    row_records, branch_total, branch_absent = build_branch_summary_rows(rows, status_codes)
    scalars = {
        "report.title": title,
        "report.date": format_display_date(as_of),
        "employee.branch": branch_name,
        "report.branch_total": str(branch_total),
        "report.branch_absent": str(branch_absent),
    }
    return scalars, row_records
