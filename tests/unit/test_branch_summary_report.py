"""Unit: агрегация «Сводка по филиалу» и каталог новых маркеров."""

from __future__ import annotations

from pathlib import Path

from domain.branch_summary import (
    build_branch_summary_context,
    build_branch_summary_rows,
    is_absent_status,
    join_employee_names,
)
from domain.roster import RosterRow
from domain.template_markers import canonical_key
from services.bootstrap import BootstrapService
from services.branch_summary_report import BranchSummaryReportService
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org


def _roster_row(
    *,
    employee_id: int,
    full_name: str,
    division_name: str,
    status_id: int | None,
    branch_id: int = 1,
    branch_name: str = "Филиал Север (тест)",
) -> RosterRow:
    return RosterRow(
        employee_id=employee_id,
        full_name=full_name,
        position_name="Инженер",
        branch_id=branch_id,
        branch_name=branch_name,
        department_id=1,
        department_name="Департамент разработки",
        division_id=1,
        division_name=division_name,
        status_id=status_id,
        status_name=None,
        status_color_hex=None,
        start_date="2026-08-01",
        end_date=None,
        needs_clarification=False,
        needs_org_review=False,
    )


def test_new_markers_resolve_from_aliases() -> None:
    assert canonical_key("отдел_всего") == "report.department_total"
    assert canonical_key("отдел_отсутствуют") == "report.department_absent"
    assert canonical_key("отпуск_ФИО") == "report.vacation_employees"
    assert canonical_key("больничный_ФИО") == "report.sick_leave_employees"
    assert canonical_key("командировка_ФИО") == "report.business_trip_employees"
    assert canonical_key("филиал_всего") == "report.branch_total"
    assert canonical_key("филиал_отсутствуют") == "report.branch_absent"
    assert canonical_key("report.department_total") == "report.department_total"
    assert canonical_key("report.branch_absent") == "report.branch_absent"


def test_is_absent_uses_existing_absence_codes() -> None:
    assert is_absent_status("vacation")
    assert is_absent_status("sick")
    assert is_absent_status("trip")
    assert is_absent_status("day_off")
    assert is_absent_status("inactive")
    assert not is_absent_status("office")
    assert not is_absent_status("remote")
    assert not is_absent_status(None)


def test_build_branch_summary_rows_groups_by_division() -> None:
    status_codes = {3: "trip", 4: "sick", 5: "vacation", 1: "office"}
    rows = [
        _roster_row(employee_id=1, full_name="Иванов И.И.", division_name="Продажи", status_id=5),
        _roster_row(employee_id=2, full_name="Петров П.П.", division_name="Продажи", status_id=5),
        _roster_row(employee_id=3, full_name="Сидоров С.С.", division_name="Продажи", status_id=4),
        _roster_row(employee_id=4, full_name="Смирнов А.А.", division_name="Продажи", status_id=3),
        _roster_row(employee_id=5, full_name="Кузнецов К.К.", division_name="Продажи", status_id=3),
        _roster_row(employee_id=6, full_name="Орлова О.О.", division_name="Бухгалтерия", status_id=5),
        _roster_row(employee_id=7, full_name="Волкова В.В.", division_name="Бухгалтерия", status_id=4),
        _roster_row(employee_id=8, full_name="Федоров Ф.Ф.", division_name="IT", status_id=5),
        _roster_row(employee_id=9, full_name="Егоров Е.Е.", division_name="IT", status_id=4),
        _roster_row(employee_id=10, full_name="Рабочий Р.Р.", division_name="IT", status_id=1),
    ]
    row_records, branch_total, branch_absent = build_branch_summary_rows(rows, status_codes)
    assert branch_total == 10
    assert branch_absent == 9
    by_division = {rec["employee.division"]: rec for rec in row_records}
    assert by_division["Продажи"]["report.department_total"] == "5"
    assert by_division["Продажи"]["report.department_absent"] == "5"
    assert by_division["Продажи"]["report.vacation_employees"] == "Иванов И.И.; Петров П.П."
    assert by_division["Продажи"]["report.sick_leave_employees"] == "Сидоров С.С."
    assert (
        by_division["Продажи"]["report.business_trip_employees"]
        == "Кузнецов К.К.; Смирнов А.А."
    )
    assert by_division["Бухгалтерия"]["report.department_total"] == "2"
    assert by_division["Бухгалтерия"]["report.business_trip_employees"] == ""
    assert by_division["IT"]["report.department_absent"] == "2"
    assert by_division["IT"]["report.department_total"] == "3"


def test_join_employee_names_sorts_and_separates() -> None:
    assert join_employee_names(["Петров П.П.", "Иванов И.И."]) == "Иванов И.И.; Петров П.П."
    assert join_employee_names([]) == ""


def test_branch_summary_service_builds_context(tmp_path: Path) -> None:
    as_of = "2026-08-15T12:00:00Z"
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: as_of).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    history = StatusHistoryService(conn, session, clock=lambda: as_of)
    history.assign_status(
        ids["employee_a_id"],
        status_id=5,
        start_date="2026-08-01",
        end_date="2026-08-31",
    )
    history.assign_status(
        ids["employee_b_id"],
        status_id=3,
        start_date="2026-08-01",
        end_date="2026-08-31",
    )
    service = BranchSummaryReportService(conn, session, clock=lambda: as_of)
    scalars, row_records = service.build_context(ids["branch_id"])
    assert scalars["employee.branch"] == "Филиал Север (тест)"
    assert scalars["report.branch_total"] == "2"
    assert scalars["report.branch_absent"] == "2"
    assert len(row_records) == 1
    assert row_records[0]["employee.division"] == "Отдел платформы"
    assert row_records[0]["report.department_total"] == "2"
    conn.close()


def test_build_branch_summary_context_scalars() -> None:
    status_codes = {5: "vacation"}
    rows = [_roster_row(employee_id=1, full_name="Иванов И.И.", division_name="Продажи", status_id=5)]
    scalars, row_records = build_branch_summary_context(
        rows,
        status_codes,
        branch_name="Центральный",
        as_of="2026-08-15",
        title="Сводка по филиалу",
    )
    assert scalars["report.title"] == "Сводка по филиалу"
    assert scalars["report.date"] == "15.08.2026"
    assert scalars["employee.branch"] == "Центральный"
    assert scalars["report.branch_total"] == "1"
    assert scalars["report.branch_absent"] == "1"
    assert row_records[0]["report.vacation_employees"] == "Иванов И.И."
