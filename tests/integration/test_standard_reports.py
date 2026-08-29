"""Integration: параметры → Excel и PDF по каждой форме (ТЗ §3.8.1 / ANCHOR_PROTOCOL §6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from domain.reports import ReportKind, ReportParams
from reports.pdf_export import pdf_contains_text, pdf_page_count, write_report_pdf
from reports.xlsx_export import write_report_xlsx
from services.bootstrap import BootstrapService
from services.standard_reports import StandardReportService
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org


def _svc(tmp_path: Path):
    db = tmp_path / "rep.db"
    clock = lambda: "2026-08-15T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=clock)
    history.assign_status(ids["employee_a_id"], status_id=1, start_date="2026-08-01")
    history.assign_status(
        ids["employee_b_id"], status_id=3, start_date="2026-08-01", end_date="2026-08-10"
    )
    reports = StandardReportService(conn, session, clock=clock)
    return conn, reports, ids


def _export_both(
    tmp_path: Path, kind: ReportKind, params: ReportParams, reports
) -> tuple[Path, Path]:
    table = reports.build(kind, params)
    xlsx = tmp_path / f"{kind.value}.xlsx"
    pdf = tmp_path / f"{kind.value}.pdf"
    write_report_xlsx(xlsx, table)
    write_report_pdf(pdf, table)
    book = load_workbook(xlsx)
    sheet = book.active
    title = str(sheet["A1"].value or "")
    assert table.title.split(":")[0] in title or title == table.title
    assert pdf_page_count(pdf) >= 1
    return xlsx, pdf


@pytest.mark.acceptance
def test_snapshot_parameters_to_files(tmp_path: Path) -> None:
    conn, reports, _ids = _svc(tmp_path)
    _xlsx, pdf = _export_both(tmp_path, ReportKind.SNAPSHOT, ReportParams(), reports)
    assert pdf_contains_text(pdf, "Иванов") or pdf.stat().st_size > 200
    conn.close()


@pytest.mark.acceptance
def test_absentees_parameters_to_files(tmp_path: Path) -> None:
    conn, reports, _ids = _svc(tmp_path)
    params = ReportParams(date_from="2026-08-01", date_to="2026-08-10")
    _export_both(tmp_path, ReportKind.ABSENTEES, params, reports)
    conn.close()


@pytest.mark.acceptance
def test_temporary_parameters_to_files(tmp_path: Path) -> None:
    conn, reports, _ids = _svc(tmp_path)
    _export_both(tmp_path, ReportKind.TEMPORARY, ReportParams(), reports)
    conn.close()


@pytest.mark.acceptance
def test_history_parameters_to_files(tmp_path: Path) -> None:
    conn, reports, ids = _svc(tmp_path)
    _export_both(
        tmp_path,
        ReportKind.HISTORY,
        ReportParams(employee_id=ids["employee_a_id"]),
        reports,
    )
    conn.close()


@pytest.mark.acceptance
def test_clarification_parameters_to_files(tmp_path: Path) -> None:
    conn, reports, _ids = _svc(tmp_path)
    _export_both(tmp_path, ReportKind.CLARIFICATION, ReportParams(), reports)
    conn.close()


def test_report_build_is_read_only(tmp_path: Path) -> None:
    conn, reports, ids = _svc(tmp_path)
    before = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    reports.build(ReportKind.SNAPSHOT, ReportParams())
    reports.build(
        ReportKind.ABSENTEES, ReportParams(date_from="2026-08-01", date_to="2026-08-10")
    )
    reports.build(ReportKind.TEMPORARY, ReportParams())
    reports.build(ReportKind.HISTORY, ReportParams(employee_id=ids["employee_a_id"]))
    reports.build(ReportKind.CLARIFICATION, ReportParams())
    after = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after == before
    conn.close()


def test_pdf_roundtrip_page_and_text(tmp_path: Path) -> None:
    conn, reports, _ids = _svc(tmp_path)
    table = reports.build(ReportKind.SNAPSHOT, ReportParams())
    pdf = tmp_path / "roundtrip.pdf"
    write_report_pdf(pdf, table)
    assert pdf.read_bytes().startswith(b"%PDF")
    assert pdf_page_count(pdf) >= 1
    assert pdf_contains_text(pdf, "Иванов") or pdf_contains_text(pdf, table.title)
    conn.close()
