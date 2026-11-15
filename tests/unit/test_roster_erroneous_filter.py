"""Unit/integration: фильтр ошибочных записей в ростере (E1-18, ТЗ §4.7.2)."""

from __future__ import annotations

from pathlib import Path

from domain.roster import RosterFilters, RosterRow, apply_filters
from services.bootstrap import BootstrapService
from services.employees import EmployeeService
from services.roster import RosterService
from tests.fixtures.synthetic import seed_synthetic_org


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
        needs_org_review=False,
        is_archived=False,
        employment_type_code="staff",
    )
    base.update(overrides)
    return RosterRow(**base)  # type: ignore[arg-type]


def test_default_filter_excludes_erroneous_rows() -> None:
    rows = [
        _row(employee_id=1, employment_type_code="staff"),
        _row(employee_id=2, employment_type_code="erroneous"),
        _row(employee_id=3, employment_type_code="dismissed"),
    ]
    got = apply_filters(rows, RosterFilters())
    assert [r.employee_id for r in got] == [1, 3]


def test_include_erroneous_keeps_erroneous_with_other_rows() -> None:
    rows = [
        _row(employee_id=1, employment_type_code="staff"),
        _row(employee_id=2, employment_type_code="erroneous"),
        _row(employee_id=3, employment_type_code="temporary"),
    ]
    got = apply_filters(rows, RosterFilters(include_erroneous=True))
    assert [r.employee_id for r in got] == [1, 2, 3]


def test_non_erroneous_rows_unchanged_when_erroneous_hidden() -> None:
    rows = [
        _row(employee_id=1, employment_type_code="staff"),
        _row(employee_id=2, employment_type_code="contractor"),
    ]
    got = apply_filters(rows, RosterFilters(include_erroneous=False))
    assert [r.employee_id for r in got] == [1, 2]


def test_erroneous_filter_combines_with_name_query() -> None:
    rows = [
        _row(employee_id=1, full_name="Иванова Мария", employment_type_code="erroneous"),
        _row(employee_id=2, full_name="Петров Алексей", employment_type_code="erroneous"),
        _row(employee_id=3, full_name="Иванов Иван", employment_type_code="staff"),
    ]
    without_flag = apply_filters(
        rows, RosterFilters(name_query="иван", include_erroneous=False)
    )
    with_flag = apply_filters(rows, RosterFilters(name_query="иван", include_erroneous=True))
    assert [r.employee_id for r in without_flag] == [3]
    assert [r.employee_id for r in with_flag] == [1, 3]


def _erroneous_employment_type_id(conn: object) -> int:
    row = conn.execute("SELECT id FROM employment_types WHERE code = 'erroneous'").fetchone()  # type: ignore[union-attr]
    assert row is not None
    return int(row[0])


def test_filters_none_without_archived_excludes_erroneous(tmp_path: Path) -> None:
    """list_rows(filters=None): без apply_filters архивные erroneous не в выдаче."""
    db = tmp_path / "app.db"
    clock = lambda: "2026-08-30T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    emp_id = ids["employee_a_id"]
    erroneous_id = _erroneous_employment_type_id(conn)
    employees = EmployeeService(conn, session, clock=clock)
    employees.archive_employee(emp_id)
    conn.execute(
        "UPDATE employees SET employment_type_id = ? WHERE id = ?",
        (erroneous_id, emp_id),
    )
    conn.commit()

    roster = RosterService(conn, session, clock=clock)
    default_rows = roster.list_rows(filters=None, include_archived=False)
    assert not any(r.employment_type_code == "erroneous" for r in default_rows)

    archived_rows = roster.list_rows(filters=None, include_archived=True)
    assert any(
        r.employee_id == emp_id and r.employment_type_code == "erroneous" for r in archived_rows
    )

    filtered = roster.list_rows(filters=RosterFilters(), include_archived=True)
    assert not any(r.employee_id == emp_id for r in filtered)
    with_erroneous = roster.list_rows(
        filters=RosterFilters(include_erroneous=True),
        include_archived=True,
    )
    assert any(
        r.employee_id == emp_id and r.employment_type_code == "erroneous" for r in with_erroneous
    )
    conn.close()


def test_list_rows_populates_employment_type_code(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    clock = lambda: "2026-08-30T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    roster = RosterService(conn, session, clock=clock)
    row = next(r for r in roster.list_rows() if r.employee_id == ids["employee_a_id"])
    assert row.employment_type_code == "staff"
    conn.close()