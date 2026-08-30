"""Integration: audit wiring for template library (EPIC-011 Steps 4–5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from domain.action_log import ENTITY_TEMPLATE, ActionLogFilters
from services.bootstrap import BootstrapService
from services.template_library import TemplateLibraryService
from services.user_action_log import UserActionLogService


def _save_excel(path: Path) -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet["A1"] = "{{ФИО}}"
    book.save(path)
    book.close()


def _open(tmp_path: Path) -> tuple[object, TemplateLibraryService, UserActionLogService]:
    clock = lambda: "2026-08-30T14:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    library = TemplateLibraryService(conn, session, data_dir=tmp_path, clock=clock)
    log = UserActionLogService(conn, session)
    return conn, library, log


def _audit_rows(conn, *, action_type: str | None = None) -> list[tuple]:
    sql = (
        "SELECT action_type, entity_type, entity_id, result, account_id, details "
        "FROM user_action_log"
    )
    params: list[object] = []
    if action_type is not None:
        sql += " WHERE action_type = ?"
        params.append(action_type)
    sql += " ORDER BY id"
    return conn.execute(sql, params).fetchall()


@pytest.mark.acceptance
def test_template_upload_audit_row(tmp_path: Path) -> None:
    conn, library, _log = _open(tmp_path)
    src = tmp_path / "tpl.xlsx"
    _save_excel(src)
    version_id = library.upload_version(name="Справка", source=src)
    rows = _audit_rows(conn, action_type="template.upload")
    assert len(rows) == 1
    action, entity_type, entity_id, result, account_id, details = rows[0]
    assert action == "template.upload"
    assert entity_type == ENTITY_TEMPLATE
    assert entity_id == 1
    assert result == "success"
    assert account_id == 1
    assert "version=1" in details
    assert "binding=excel" in details
    assert version_id == 1
    conn.close()


@pytest.mark.acceptance
def test_template_archive_and_restore_audit_rows(tmp_path: Path) -> None:
    conn, library, _log = _open(tmp_path)
    src = tmp_path / "tpl.xlsx"
    _save_excel(src)
    library.upload_version(name="X", source=src)
    library.archive_template(1)
    library.restore_template(1)
    archive = _audit_rows(conn, action_type="template.archive")
    restore = _audit_rows(conn, action_type="template.restore")
    assert len(archive) == 1
    assert len(restore) == 1
    assert archive[0][2] == 1
    assert restore[0][2] == 1
    conn.close()


@pytest.mark.acceptance
def test_template_generate_audit_row(tmp_path: Path) -> None:
    conn, library, _log = _open(tmp_path)
    src = tmp_path / "tpl.xlsx"
    _save_excel(src)
    version_id = library.upload_version(name="Gen", source=src)
    out = tmp_path / "out.xlsx"
    library.generate_report(version_id, out, values={"employee.full_name": "X"})
    rows = _audit_rows(conn, action_type="template.generate")
    assert len(rows) == 1
    assert rows[0][1] == ENTITY_TEMPLATE
    assert rows[0][2] == 1
    assert "version=1" in rows[0][5]
    assert str(out) in rows[0][5]
    conn.close()


@pytest.mark.acceptance
def test_template_list_reads_write_no_audit(tmp_path: Path) -> None:
    conn, library, _log = _open(tmp_path)
    src = tmp_path / "tpl.xlsx"
    _save_excel(src)
    library.upload_version(name="ReadOnly", source=src)
    before = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    library.list_templates()
    library.list_templates(active_only=True)
    library.list_versions(1)
    after = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after == before
    conn.close()


@pytest.mark.acceptance
def test_journal_template_filter_surfaces_template_operations(tmp_path: Path) -> None:
    """PR #13 connection test: upload → archive → generate → journal filter."""
    conn, library, log = _open(tmp_path)
    src = tmp_path / "tpl.xlsx"
    _save_excel(src)
    version_id = library.upload_version(name="Журнальный", source=src)
    library.archive_template(1)
    library.restore_template(1)
    out = tmp_path / "report.xlsx"
    library.generate_report(version_id, out, values={})

    templates = log.list_templates()
    assert templates == [(1, "Журнальный")]

    filtered = log.list_entries(ActionLogFilters(template_id=1))
    assert {e.action_type for e in filtered} == {
        "template.upload",
        "template.archive",
        "template.restore",
        "template.generate",
    }
    assert all(e.entity_type == ENTITY_TEMPLATE for e in filtered)
    assert all(e.entity_id == 1 for e in filtered)

    by_upload = log.list_entries(
        ActionLogFilters(template_id=1, action_type="template.upload")
    )
    assert len(by_upload) == 1
    assert "binding=excel" in (by_upload[0].details or "")

    conn.close()
