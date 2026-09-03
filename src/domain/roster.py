"""Фильтрация, поиск и группировка главного экрана (ТЗ §3.4–3.6) — без Qt и БД."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

UNASSIGNED_COLUMN_ID = -1
UNASSIGNED_COLUMN_TITLE = "Требует уточнения"


class GroupBy(StrEnum):
    STATUS = "status"
    BRANCH = "branch"
    DEPARTMENT = "department"


@dataclass(frozen=True)
class RosterRow:
    employee_id: int
    full_name: str
    position_name: str
    branch_id: int
    branch_name: str
    department_id: int
    department_name: str
    division_id: int | None
    division_name: str | None
    status_id: int | None
    status_name: str | None
    status_color_hex: str | None
    start_date: str | None
    end_date: str | None
    needs_clarification: bool


@dataclass(frozen=True)
class RosterFilters:
    name_query: str = ""
    branch_id: int | None = None
    department_id: int | None = None
    division_id: int | None = None
    only_needing_clarification: bool = False


@dataclass(frozen=True)
class RosterColumn:
    key: int
    title: str
    color_hex: str | None
    rows: tuple[RosterRow, ...]


@dataclass(frozen=True)
class HistoryPreviewRow:
    start_date: str
    end_date: str | None
    status_name: str


@dataclass(frozen=True)
class ColumnSpec:
    key: int
    title: str
    color_hex: str | None = None


def format_display_date(iso_date: str | None) -> str:
    if not iso_date:
        return "—"
    year, month, day = iso_date.split("-")
    return f"{day}.{month}.{year}"


def _normalize_name_for_search(value: str) -> str:
    """Подстрочный поиск без учёта регистра; «ё» и «е» считаются одним символом."""
    return value.strip().casefold().replace("ё", "е")


def apply_filters(rows: list[RosterRow], filters: RosterFilters) -> list[RosterRow]:
    query = _normalize_name_for_search(filters.name_query)
    out: list[RosterRow] = []
    for row in rows:
        if query and query not in _normalize_name_for_search(row.full_name):
            continue
        if filters.branch_id is not None and row.branch_id != filters.branch_id:
            continue
        if filters.department_id is not None and row.department_id != filters.department_id:
            continue
        if filters.division_id is not None and row.division_id != filters.division_id:
            continue
        if filters.only_needing_clarification and not row.needs_clarification:
            continue
        out.append(row)
    return out


def summary_counts(rows: list[RosterRow]) -> tuple[int, dict[str, int], int]:
    by_status: dict[str, int] = {}
    needing = 0
    for row in rows:
        if row.needs_clarification:
            needing += 1
        if row.status_name:
            by_status[row.status_name] = by_status.get(row.status_name, 0) + 1
    return len(rows), by_status, needing


def group_rows(
    rows: list[RosterRow],
    group_by: GroupBy,
    columns: list[ColumnSpec],
) -> list[RosterColumn]:
    buckets: dict[int, list[RosterRow]] = {spec.key: [] for spec in columns}
    extras: list[RosterRow] = []
    for row in rows:
        key = _group_key(row, group_by)
        if key in buckets:
            buckets[key].append(row)
        else:
            extras.append(row)
    result = [
        RosterColumn(
            key=spec.key,
            title=spec.title,
            color_hex=spec.color_hex,
            rows=tuple(buckets[spec.key]),
        )
        for spec in columns
    ]
    if extras:
        result.append(
            RosterColumn(
                key=UNASSIGNED_COLUMN_ID,
                title=UNASSIGNED_COLUMN_TITLE,
                color_hex="#A32D2D",
                rows=tuple(extras),
            )
        )
    return result


def _group_key(row: RosterRow, group_by: GroupBy) -> int:
    if group_by == GroupBy.STATUS:
        return row.status_id if row.status_id is not None else UNASSIGNED_COLUMN_ID
    if group_by == GroupBy.BRANCH:
        return row.branch_id
    return row.department_id
