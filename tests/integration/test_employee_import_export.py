"""Integration: импорт с предпросмотром и сырой экспорт XLSX (ТЗ §3.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.employee_import import EXPORT_HEADERS, SENSITIVE_EXPORT_HEADERS
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employee_export import EmployeeExportService
from services.employee_files import read_tabular
from services.employee_import import EmployeeImportService
from services.employees import EmployeeService
from services.roster import RosterService
from services.session import SessionState
from tests.fixtures.synthetic import seed_synthetic_org


def _open(tmp_path: Path):
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-27T12:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    ids = seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=lambda: "2026-08-27T12:00:00Z")
    directories = DirectoryService(conn, session, clock=lambda: "2026-08-27T12:00:00Z")
    importer = EmployeeImportService(employees, directories, session)
    exporter = EmployeeExportService(employees, directories, session)
    return conn, session, employees, directories, importer, exporter, ids, db


def _new_row() -> list[str]:
    return [
        "Кузнецова Ольга",
        "Инженер",
        "Филиал Север (тест)",
        "Департамент разработки",
        "Отдел платформы",
        "Штатный",
    ]


@pytest.mark.acceptance
def test_import_preview_confirm_appears_in_roster(tmp_path: Path) -> None:
    conn, session, _emp, _dirs, importer, _exp, _ids, _db = _open(tmp_path)
    path = tmp_path / "in.csv"
    path.write_text(
        "ФИО,Должность,Филиал,Департамент,Отдел,Тип занятости\n"
        + ",".join(_new_row())
        + "\n",
        encoding="utf-8",
    )
    before_audit = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    preview = importer.preview_path(path)
    after_preview = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after_preview == before_audit
    assert len(preview.ready) == 1
    assert not preview.errors
    created = importer.confirm(preview)
    assert len(created) == 1
    roster = RosterService(conn, session, clock=lambda: "2026-08-27T12:00:00Z")
    names = {row.full_name for row in roster.list_rows()}
    assert "Кузнецова Ольга" in names
    creates = conn.execute(
        "SELECT COUNT(*) FROM user_action_log WHERE action_type = 'employee.create'"
        " AND entity_id = ?",
        (created[0],),
    ).fetchone()[0]
    assert creates == 1
    conn.close()


@pytest.mark.acceptance
def test_rejected_preview_writes_nothing(tmp_path: Path) -> None:
    conn, _session, _emp, _dirs, importer, _exp, _ids, _db = _open(tmp_path)
    before_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    before_audit = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    preview = importer.preview_rows(
        list(EXPORT_HEADERS),
        [["Петров", "Инженер", "Нет филиала", "Нет", "Нет", "Штатный"]],
    )
    assert preview.errors
    assert not preview.ready
    after_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    after_audit = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after_emp == before_emp
    assert after_audit == before_audit
    conn.close()


def test_duplicate_name_subdivision_is_warning_not_error(tmp_path: Path) -> None:
    conn, _session, _emp, _dirs, importer, _exp, _ids, _db = _open(tmp_path)
    preview = importer.preview_rows(
        list(EXPORT_HEADERS),
        [
            [
                "Иванов Иван Иванович",
                "Инженер",
                "Филиал Север (тест)",
                "Департамент разработки",
                "Отдел платформы",
                "Штатный",
            ]
        ],
    )
    assert preview.ready
    assert preview.warnings
    assert not preview.errors
    assert "duplicate" in preview.warnings[0].message
    conn.close()


def test_export_xlsx_expected_columns_and_hr_omits_sensitive(tmp_path: Path) -> None:
    conn, admin, _emp, _dirs, _imp, exporter, _ids, db = _open(tmp_path)
    admin_path = tmp_path / "admin.xlsx"
    exporter.export_xlsx(admin_path)
    headers, rows = read_tabular(admin_path)
    assert tuple(headers[:6]) == EXPORT_HEADERS
    assert SENSITIVE_EXPORT_HEADERS[0] in headers
    assert len(rows) == 2
    assert any(row[0] == "Иванов Иван Иванович" for row in rows)
    assert any(cell for row in rows for cell in row[6:])

    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-08-27T12:10:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    hr = SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin.master_key,
    )
    hr_emp = EmployeeService(conn, hr, clock=lambda: "2026-08-27T12:11:00Z")
    hr_dirs = DirectoryService(conn, hr, clock=lambda: "2026-08-27T12:11:00Z")
    hr_path = tmp_path / "hr.xlsx"
    EmployeeExportService(hr_emp, hr_dirs, hr).export_xlsx(hr_path)
    hr_headers, _hr_rows = read_tabular(hr_path)
    assert tuple(hr_headers) == EXPORT_HEADERS
    assert SENSITIVE_EXPORT_HEADERS[0] not in hr_headers
    conn.close()


def test_export_import_roundtrip_file_shape(tmp_path: Path) -> None:
    conn, _session, _emp, _dirs, importer, exporter, _ids, _db = _open(tmp_path)
    path = tmp_path / "roundtrip.xlsx"
    exporter.export_xlsx(path)
    headers, rows = read_tabular(path)
    assert tuple(headers[:6]) == EXPORT_HEADERS
    preview = importer.preview_rows(headers, [row[:6] for row in rows])
    assert len(preview.ready) == 2
    assert preview.warnings
    conn.close()


def test_observer_cannot_import(tmp_path: Path) -> None:
    conn, admin, _emp, _dirs, _imp, _exp, _ids, db = _open(tmp_path)
    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-08-27T12:20:00Z"
    )
    obs_id = mgr.create_account(
        login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER
    )
    obs = SessionState(
        account_id=obs_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=admin.master_key,
    )
    employees = EmployeeService(conn, obs)
    directories = DirectoryService(conn, obs)
    importer = EmployeeImportService(employees, directories, obs)
    with pytest.raises(AuthorizationError):
        importer.preview_rows(list(EXPORT_HEADERS), [_new_row()])
    conn.close()
