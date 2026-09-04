"""EPIC-016: нагрузочная приёмка на синтетической базе ~400 сотрудников (TESTING §2.8)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from domain.employee import EmployeeCreateInput
from domain.reports import ReportKind, ReportParams
from reports.excel_template import archive_upload, generate_excel_report, validate_archived
from reports.xlsx_export import write_report_xlsx
from services.bootstrap import BootstrapService
from services.employees import EmployeeService
from services.roster import RosterService
from services.standard_reports import StandardReportService
from services.status_history import StatusHistoryService
from tests.fixtures.generate_perf_dataset import seed_perf_dataset

_SAMPLES = Path(__file__).resolve().parents[2] / "templates_samples" / "sample_report.xlsx"
_CLOCK = lambda: "2026-08-15T12:00:00Z"  # noqa: E731
_EMPLOYEE_COUNT = 400


def _open_large(tmp_path: Path):
    db = tmp_path / "perf.db"
    conn, session, _code = BootstrapService(clock=_CLOCK).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    info = seed_perf_dataset(conn, employee_count=_EMPLOYEE_COUNT, account_id=1)
    return conn, session, info


def _elapsed(start: float) -> float:
    return time.perf_counter() - start


@pytest.mark.acceptance
def test_perf_search_roster_on_large_dataset(tmp_path: Path) -> None:
    conn, session, info = _open_large(tmp_path)
    employees = EmployeeService(conn, session, clock=_CLOCK)
    roster = RosterService(conn, session, clock=_CLOCK)

    t0 = time.perf_counter()
    hits = employees.search_by_name("Тест")
    search_s = _elapsed(t0)
    assert len(hits) == 50

    t0 = time.perf_counter()
    rows = roster.list_rows(as_of="2026-08-15")
    roster_s = _elapsed(t0)
    assert len(rows) == info["employee_count"]

    card = employees.list_employees(active_only=True)
    assert len(card) == info["employee_count"]
    assert search_s < 30.0, f"search took {search_s:.2f}s"
    assert roster_s < 30.0, f"roster took {roster_s:.2f}s"
    conn.close()


@pytest.mark.acceptance
def test_perf_status_change_and_standard_report(tmp_path: Path) -> None:
    conn, session, info = _open_large(tmp_path)
    history = StatusHistoryService(conn, session, clock=_CLOCK)
    reports = StandardReportService(conn, session, clock=_CLOCK)

    t0 = time.perf_counter()
    history.assign_status(1, status_id=2, start_date="2026-08-15")
    status_s = _elapsed(t0)

    t0 = time.perf_counter()
    table = reports.build(ReportKind.SNAPSHOT, ReportParams())
    report_s = _elapsed(t0)
    assert len(table.rows) >= 1

    out = tmp_path / "snapshot.xlsx"
    write_report_xlsx(out, table)
    assert out.stat().st_size > 0
    assert status_s < 15.0, f"status assign took {status_s:.2f}s"
    assert report_s < 60.0, f"report build took {report_s:.2f}s"
    conn.close()


@pytest.mark.acceptance
def test_perf_template_report_on_large_dataset(tmp_path: Path) -> None:
    conn, session, _info = _open_large(tmp_path)
    validate_archived(_SAMPLES)
    archive = tmp_path / "archive.xlsx"
    archived = archive_upload(_SAMPLES, archive)
    out = tmp_path / "template_out.xlsx"

    t0 = time.perf_counter()
    generate_excel_report(
        archived,
        out,
        scalars={"report.title": "Нагрузочный отчёт", "report.period_from": "2026-08-01"},
        row_records=[{"employee.full_name": "Тестов Тест Т001", "employee.position": "Инженер"}],
    )
    template_s = _elapsed(t0)
    assert out.is_file()
    assert template_s < 30.0, f"template generate took {template_s:.2f}s"
    conn.close()


@pytest.mark.acceptance
def test_perf_create_employee_on_large_dataset(tmp_path: Path) -> None:
    conn, session, info = _open_large(tmp_path)
    employees = EmployeeService(conn, session, clock=_CLOCK)
    payload = EmployeeCreateInput(
        full_name="Новый Сотрудник Нагрузка",
        position_id=1,
        branch_id=info["branch_id"],
        department_id=info["department_id"],
        division_id=info["division_id"],
        employment_type_id=1,
    )
    t0 = time.perf_counter()
    new_id = employees.create_employee(payload)
    create_s = _elapsed(t0)
    assert new_id > info["employee_count"]
    assert create_s < 15.0, f"create employee took {create_s:.2f}s"
    conn.close()
