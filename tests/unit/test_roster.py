"""Unit: фильтры, поиск и группировка главного экрана (ТЗ §3.4–3.6)."""

from __future__ import annotations

from domain.roster import (
    UNASSIGNED_COLUMN_ID,
    ColumnSpec,
    GroupBy,
    RosterFilters,
    RosterRow,
    apply_filters,
    format_display_date,
    group_rows,
    summary_counts,
)


def _row(**overrides: object) -> RosterRow:
    base = dict(
        employee_id=1,
        full_name="Иванова Мария",
        position_name="Бухгалтер",
        branch_id=1,
        branch_name="Москва",
        department_id=10,
        department_name="Финансы",
        division_id=100,
        division_name="Бухгалтерия",
        status_id=1,
        status_name="В офисе",
        status_color_hex="#2E6B28",
        start_date="2026-08-13",
        end_date=None,
        needs_clarification=False,
    )
    base.update(overrides)
    return RosterRow(**base)  # type: ignore[arg-type]


def test_name_search_is_case_insensitive() -> None:
    rows = [_row(), _row(employee_id=2, full_name="Петров Алексей")]
    got = apply_filters(rows, RosterFilters(name_query="иванов"))
    assert [r.employee_id for r in got] == [1]


def test_cascading_org_filters() -> None:
    rows = [
        _row(),
        _row(employee_id=2, branch_id=2, branch_name="СПб", department_id=20),
    ]
    got = apply_filters(rows, RosterFilters(branch_id=1, department_id=10))
    assert [r.employee_id for r in got] == [1]


def test_clarification_filter() -> None:
    rows = [_row(), _row(employee_id=2, needs_clarification=True, status_id=3)]
    got = apply_filters(rows, RosterFilters(only_needing_clarification=True))
    assert [r.employee_id for r in got] == [2]


def test_group_by_status_keeps_empty_columns() -> None:
    rows = [_row()]
    columns = group_rows(
        rows,
        GroupBy.STATUS,
        [
            ColumnSpec(1, "В офисе", "#2E6B28"),
            ColumnSpec(2, "Удалённо", "#1E5F8C"),
        ],
    )
    assert [c.title for c in columns] == ["В офисе", "Удалённо"]
    assert len(columns[0].rows) == 1
    assert len(columns[1].rows) == 0


def test_no_status_goes_to_clarification_column() -> None:
    rows = [_row(status_id=None, status_name=None, needs_clarification=True)]
    columns = group_rows(rows, GroupBy.STATUS, [ColumnSpec(1, "В офисе")])
    assert columns[-1].key == UNASSIGNED_COLUMN_ID
    assert columns[-1].rows[0].employee_id == 1


def test_group_by_branch() -> None:
    rows = [
        _row(),
        _row(employee_id=2, branch_id=2, branch_name="СПб"),
    ]
    columns = group_rows(
        rows,
        GroupBy.BRANCH,
        [ColumnSpec(1, "Москва"), ColumnSpec(2, "СПб")],
    )
    assert len(columns[0].rows) == 1
    assert len(columns[1].rows) == 1


def test_summary_counts() -> None:
    rows = [
        _row(),
        _row(employee_id=2, status_name="Удалённо", needs_clarification=True),
    ]
    total, by_status, needing = summary_counts(rows)
    assert total == 2
    assert by_status["В офисе"] == 1
    assert needing == 1


def test_display_date_format() -> None:
    assert format_display_date("2026-08-13") == "13.08.2026"
    assert format_display_date(None) == "—"
