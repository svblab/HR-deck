"""Integration: библиотека шаблонов — версии, архив, linkage (EPIC-011 Step 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.template_library import TemplateLibraryError, TemplateLibraryService


def _save_excel(path: Path, marker: str = "{{ФИО}}") -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet["A1"] = marker
    book.save(path)
    book.close()


def _open(
    tmp_path: Path,
) -> tuple[object, SessionState, TemplateLibraryService, AccountManagementService]:
    clock = lambda: "2026-08-30T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    library = TemplateLibraryService(conn, session, data_dir=tmp_path, clock=clock)
    accounts = AccountManagementService(
        conn, session, db_path=tmp_path / "app.db", clock=clock
    )
    return conn, session, library, accounts


@pytest.mark.acceptance
def test_template_version_auto_increment(tmp_path: Path) -> None:
    conn, _session, library, _accounts = _open(tmp_path)
    src1 = tmp_path / "v1.xlsx"
    src2 = tmp_path / "v2.xlsx"
    _save_excel(src1)
    _save_excel(src2, "{{должность}}")
    v1 = library.upload_version(name="Отчёт", source=src1)
    v2 = library.upload_version(name="Отчёт", source=src2, template_id=1)
    versions = library.list_versions(1)
    assert [v.version_number for v in versions] == [1, 2]
    assert v1 != v2
    conn.close()


@pytest.mark.acceptance
def test_adr0005_generated_report_pinned_to_template_version(tmp_path: Path) -> None:
    conn, session, library, _accounts = _open(tmp_path)
    src = tmp_path / "tpl.xlsx"
    _save_excel(src)
    version_id = library.upload_version(name="Справка", source=src)
    out = tmp_path / "out.xlsx"
    record = library.generate_report(version_id, out, values={"employee.full_name": "Иванов"})
    row = conn.execute(
        "SELECT template_version_id, output_path, generated_by_account_id "
        "FROM template_generated_reports WHERE id = ?",
        (record.id,),
    ).fetchone()
    assert row is not None
    assert row[0] == version_id
    assert row[1] == str(out)
    assert row[2] == session.account_id
    assert out.is_file()
    conn.close()


@pytest.mark.acceptance
def test_archive_hides_from_active_but_keeps_generated_links(tmp_path: Path) -> None:
    conn, _session, library, _accounts = _open(tmp_path)
    src = tmp_path / "tpl.xlsx"
    _save_excel(src)
    version_id = library.upload_version(name="Скрываемый", source=src)
    out = tmp_path / "out.xlsx"
    library.generate_report(version_id, out, values={})
    library.archive_template(1)
    active = library.list_templates(active_only=True)
    assert active == []
    all_templates = library.list_templates(active_only=False)
    assert len(all_templates) == 1
    assert all_templates[0].is_archived
    count = conn.execute("SELECT COUNT(*) FROM template_generated_reports").fetchone()[0]
    assert count == 1
    library.restore_template(1)
    assert len(library.list_templates(active_only=True)) == 1
    conn.close()


@pytest.mark.acceptance
def test_generate_rejects_archived_template(tmp_path: Path) -> None:
    conn, _session, library, _accounts = _open(tmp_path)
    src = tmp_path / "tpl.xlsx"
    _save_excel(src)
    version_id = library.upload_version(name="X", source=src)
    library.archive_template(1)
    with pytest.raises(TemplateLibraryError, match="archived"):
        library.generate_report(version_id, tmp_path / "out.xlsx", values={})
    conn.close()


@pytest.mark.acceptance
def test_template_library_rbac(tmp_path: Path) -> None:
    conn, admin, library, accounts = _open(tmp_path)
    src = tmp_path / "tpl.xlsx"
    _save_excel(src)
    version_id = library.upload_version(name="RBAC", source=src)

    hr_id = accounts.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    hr = SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin.master_key,
    )
    hr_library = TemplateLibraryService(conn, hr, data_dir=tmp_path)
    assert hr_library.list_templates()
    hr_library.generate_report(version_id, tmp_path / "hr.xlsx", values={})
    with pytest.raises(AuthorizationError):
        hr_library.upload_version(name="Nope", source=src)

    obs_id = accounts.create_account(login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER)
    obs = SessionState(
        account_id=obs_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=admin.master_key,
    )
    obs_library = TemplateLibraryService(conn, obs, data_dir=tmp_path)
    obs_library.generate_report(version_id, tmp_path / "obs.xlsx", values={})
    with pytest.raises(AuthorizationError):
        obs_library.archive_template(1)
    conn.close()
