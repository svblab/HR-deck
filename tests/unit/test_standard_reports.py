"""Unit: выборка строк стандартных отчётов (ТЗ §3.8.1)."""

from __future__ import annotations

from pathlib import Path

from domain.reports import ReportKind, ReportParam, ReportParams, uses_param
from services.bootstrap import BootstrapService
from services.standard_reports import StandardReportService
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org


def _svc(tmp_path: Path, as_of: str = "2026-08-15T12:00:00Z"):
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: as_of).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=lambda: as_of)
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    history.assign_status(
        ids["employee_b_id"],
        status_id=3,
        start_date="2026-08-01",
        end_date="2026-08-10",
    )
    reports = StandardReportService(conn, session, clock=lambda: as_of)
    return conn, session, reports, ids, history


def test_spec_declares_params_per_report() -> None:
    assert uses_param(ReportKind.SNAPSHOT, ReportParam.GROUP_BY)
    assert not uses_param(ReportKind.TEMPORARY, ReportParam.GROUP_BY)
    assert uses_param(ReportKind.HISTORY, ReportParam.EMPLOYEE)
    assert uses_param(ReportKind.ABSENTEES, ReportParam.PERIOD)


def test_snapshot_groups_and_filters(tmp_path: Path) -> None:
    conn, _session, reports, ids, _h = _svc(tmp_path)
    table = reports.build(ReportKind.SNAPSHOT, ReportParams())
    names = {row.cells[0] for row in table.rows}
    assert "Иванов Иван Иванович" in names
    assert all(row.group_label for row in table.rows)
    filtered = reports.build(ReportKind.SNAPSHOT, ReportParams(status_id=1))
    assert all(row.cells[2] == "В офисе" for row in filtered.rows)
    conn.close()


def test_absentees_empty_range_single_day_and_boundary(tmp_path: Path) -> None:
    conn, _session, reports, ids, history = _svc(tmp_path)
    empty = reports.build(
        ReportKind.ABSENTEES,
        ReportParams(date_from="2026-08-20", date_to="2026-08-10"),
    )
    assert empty.rows == ()
    one_day = reports.build(
        ReportKind.ABSENTEES,
        ReportParams(date_from="2026-08-05", date_to="2026-08-05"),
    )
    assert any(row.cells[0] == "Иванов Иван Иванович" for row in one_day.rows)
    history.assign_status(
        ids["employee_a_id"], status_id=4, start_date="2026-08-10", end_date="2026-08-12"
    )
    boundary = reports.build(
        ReportKind.ABSENTEES,
        ReportParams(date_from="2026-08-09", date_to="2026-08-11"),
    )
    statuses = {row.cells[2] for row in boundary.rows}
    assert "Больничный" in statuses
    conn.close()


def test_temporary_selects_temporary_employment(tmp_path: Path) -> None:
    conn, _session, reports, ids, _h = _svc(tmp_path)
    table = reports.build(ReportKind.TEMPORARY, ReportParams())
    assert len(table.rows) == 1
    conn.close()
    del ids


def test_history_for_one_employee(tmp_path: Path) -> None:
    conn, _session, reports, ids, _h = _svc(tmp_path)
    empty = reports.build(ReportKind.HISTORY, ReportParams())
    assert empty.rows == ()
    table = reports.build(ReportKind.HISTORY, ReportParams(employee_id=ids["employee_a_id"]))
    assert table.rows
    assert table.rows[0].cells[0] == "В офисе"
    clipped = reports.build(
        ReportKind.HISTORY,
        ReportParams(
            employee_id=ids["employee_a_id"],
            date_from="2026-07-01",
            date_to="2026-07-31",
        ),
    )
    assert clipped.rows == ()
    conn.close()


def test_clarification_report_lists_expired(tmp_path: Path) -> None:
    conn, _session, reports, ids, _h = _svc(tmp_path)
    table = reports.build(ReportKind.CLARIFICATION, ReportParams())
    assert len(table.rows) == 1
    assert table.rows[0].cells[0] == "Иванов Иван Иванович"
    assert table.rows[0].group_label
    conn.close()
    del ids
