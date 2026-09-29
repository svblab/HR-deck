"""Unit: conversion bulk readiness classification (EPIC-018 / Issue #124)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.import_sessions import ImportSessionRepository
from services.bootstrap import BootstrapService
from services.conversion_bulk_readiness import classify_conversion_rows
from services.directories import DirectoryService
from services.employees import EmployeeService
from tests.fixtures.synthetic import seed_synthetic_org


def _open(tmp_path: Path):
    clock = lambda: "2026-09-25T10:00:00Z"  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=clock)
    directories = DirectoryService(conn, session, clock=clock)
    sessions = ImportSessionRepository(conn)
    return conn, employees, directories, sessions, ids


def _stage(sessions, conn, values: dict, *, row_number: int = 2) -> int:
    session_id = sessions.create_session(
        file_content_hash="d" * 64, last_accessed_at="2026-09-25T09:00:00Z"
    )
    sessions.insert_row(
        session_id=session_id,
        source_row_number=row_number,
        values_json=json.dumps(values, ensure_ascii=False),
    )
    conn.commit()
    return session_id


def _ready_row(**overrides: str) -> dict[str, str]:
    base = {
        "full_name": "Новый Конверт",
        "branch": "Филиал Север (тест)",
        "department": "Департамент разработки",
        "division": "Отдел платформы",
        "position": "Инженер",
        "employment_type": "Штатный",
    }
    base.update(overrides)
    return base


@pytest.mark.acceptance
def test_fully_matching_row_is_ready(tmp_path: Path) -> None:
    conn, employees, directories, sessions, _ids = _open(tmp_path)
    session_id = _stage(sessions, conn, _ready_row())
    rows = sessions.list_rows(session_id)
    classified = classify_conversion_rows(rows, directories=directories, employees=employees)
    assert len(classified) == 1
    assert classified[0].kind == "ready"
    assert classified[0].resolved is not None
    conn.close()


@pytest.mark.acceptance
def test_casefold_exact_matching_is_ready(tmp_path: Path) -> None:
    conn, employees, directories, sessions, _ids = _open(tmp_path)
    session_id = _stage(
        sessions,
        conn,
        _ready_row(
            branch="  филиал север (тест)  ",
            position="инженер",
            employment_type="штатный",
        ),
    )
    classified = classify_conversion_rows(
        sessions.list_rows(session_id), directories=directories, employees=employees
    )
    assert classified[0].kind == "ready"
    conn.close()


@pytest.mark.acceptance
def test_archived_branch_needs_review(tmp_path: Path) -> None:
    conn, employees, directories, sessions, ids = _open(tmp_path)
    directories.archive_branch(ids["branch_id"])
    conn.commit()
    session_id = _stage(sessions, conn, _ready_row())
    classified = classify_conversion_rows(
        sessions.list_rows(session_id), directories=directories, employees=employees
    )
    assert classified[0].kind == "needs_review"
    conn.close()


@pytest.mark.acceptance
def test_unmatched_branch_needs_review(tmp_path: Path) -> None:
    conn, employees, directories, sessions, _ids = _open(tmp_path)
    session_id = _stage(sessions, conn, _ready_row(branch="Несуществующий филиал"))
    classified = classify_conversion_rows(
        sessions.list_rows(session_id), directories=directories, employees=employees
    )
    assert classified[0].kind == "needs_review"
    conn.close()


@pytest.mark.acceptance
def test_unmatched_position_needs_review(tmp_path: Path) -> None:
    conn, employees, directories, sessions, _ids = _open(tmp_path)
    session_id = _stage(sessions, conn, _ready_row(position="Несуществующая должность"))
    classified = classify_conversion_rows(
        sessions.list_rows(session_id), directories=directories, employees=employees
    )
    assert classified[0].kind == "needs_review"
    conn.close()


@pytest.mark.acceptance
def test_unmatched_employment_type_needs_review(tmp_path: Path) -> None:
    conn, employees, directories, sessions, _ids = _open(tmp_path)
    session_id = _stage(sessions, conn, _ready_row(employment_type="Несуществующий тип"))
    classified = classify_conversion_rows(
        sessions.list_rows(session_id), directories=directories, employees=employees
    )
    assert classified[0].kind == "needs_review"
    conn.close()


@pytest.mark.acceptance
def test_unmatched_department_needs_review(tmp_path: Path) -> None:
    conn, employees, directories, sessions, _ids = _open(tmp_path)
    session_id = _stage(sessions, conn, _ready_row(department="Несуществующий департамент"))
    classified = classify_conversion_rows(
        sessions.list_rows(session_id), directories=directories, employees=employees
    )
    assert classified[0].kind == "needs_review"
    conn.close()


@pytest.mark.acceptance
def test_empty_department_and_division_ready(tmp_path: Path) -> None:
    conn, employees, directories, sessions, _ids = _open(tmp_path)
    session_id = _stage(
        sessions,
        conn,
        _ready_row(department="", division=""),
    )
    classified = classify_conversion_rows(
        sessions.list_rows(session_id), directories=directories, employees=employees
    )
    assert classified[0].kind == "ready"
    assert classified[0].resolved is not None
    assert classified[0].resolved.department_id is None
    assert classified[0].resolved.division_id is None
    conn.close()


@pytest.mark.acceptance
def test_missing_required_full_name_needs_review(tmp_path: Path) -> None:
    conn, employees, directories, sessions, _ids = _open(tmp_path)
    session_id = _stage(sessions, conn, _ready_row(full_name="   "))
    classified = classify_conversion_rows(
        sessions.list_rows(session_id), directories=directories, employees=employees
    )
    assert classified[0].kind == "needs_review"
    conn.close()


@pytest.mark.acceptance
def test_duplicate_name_needs_review(tmp_path: Path) -> None:
    conn, employees, directories, sessions, _ids = _open(tmp_path)
    session_id = _stage(sessions, conn, _ready_row(full_name="Иванов Иван Иванович"))
    classified = classify_conversion_rows(
        sessions.list_rows(session_id), directories=directories, employees=employees
    )
    assert classified[0].kind == "needs_review"
    conn.close()
