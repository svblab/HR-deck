"""Integration: EmployeeService commit seam and EmployeeConversionService (EPIC-018)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.employees import EmployeeRepository
from data.import_sessions import ImportSessionRepository
from domain.employee import EmployeeCreateInput
from services.bootstrap import BootstrapService
from services.employee_conversion import EmployeeConversionService
from services.employees import EmployeeService
from tests.fixtures.synthetic import seed_synthetic_org

_HASH = "c" * 64
_T0 = "2026-09-25T10:00:00Z"
_T1 = "2026-09-25T11:00:00Z"
_JSON = '{"full_name":"Новый Сотрудник"}'


def _open(tmp_path: Path):
    clock = lambda: _T0  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=clock)
    sessions = ImportSessionRepository(conn)
    conversion = EmployeeConversionService(conn, session, employees, sessions=sessions)
    return conn, session, employees, sessions, conversion, ids


def _employee_payload(ids: dict[str, int], *, full_name: str = "Новый Сотрудник") -> EmployeeCreateInput:
    return EmployeeCreateInput(
        full_name=full_name,
        position_id=ids["position_engineer_id"],
        branch_id=ids["branch_id"],
        department_id=ids["department_id"],
        division_id=ids["division_id"],
        employment_type_id=1,
    )


def _audit_count(conn, *, entity_id: int | None = None) -> int:
    if entity_id is None:
        row = conn.execute(
            "SELECT COUNT(*) FROM user_action_log WHERE action_type = 'employee.create'"
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM user_action_log"
            " WHERE action_type = 'employee.create' AND entity_id = ?",
            (entity_id,),
        ).fetchone()
    return int(row[0])


def _stage_row(
    sessions: ImportSessionRepository, conn, *, row_number: int = 2
) -> tuple[int, int]:
    session_id = sessions.create_session(file_content_hash=_HASH, last_accessed_at=_T0)
    row_id = sessions.insert_row(
        session_id=session_id,
        source_row_number=row_number,
        values_json=_JSON,
    )
    conn.commit()
    return session_id, row_id


@pytest.mark.acceptance
def test_create_employee_commit_true_unchanged(tmp_path: Path) -> None:
    conn, _session, employees, _sessions, _conversion, ids = _open(tmp_path)
    before = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    emp_id = employees.create_employee(_employee_payload(ids))
    assert emp_id > 0
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before + 1
    assert _audit_count(conn, entity_id=emp_id) == 1
    conn.close()


@pytest.mark.acceptance
def test_create_employee_commit_false_rollback(tmp_path: Path) -> None:
    conn, _session, employees, _sessions, _conversion, ids = _open(tmp_path)
    before_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    before_audit = _audit_count(conn)

    emp_id = employees.create_employee(_employee_payload(ids), commit=False)
    assert EmployeeRepository(conn).get(emp_id) is not None
    assert _audit_count(conn, entity_id=emp_id) == 1

    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before_emp
    assert _audit_count(conn) == before_audit
    conn.close()


@pytest.mark.acceptance
def test_create_employee_commit_false_then_commit(tmp_path: Path) -> None:
    conn, _session, employees, _sessions, _conversion, ids = _open(tmp_path)
    before = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]

    emp_id = employees.create_employee(_employee_payload(ids), commit=False)
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before + 1
    assert _audit_count(conn, entity_id=emp_id) == 1
    conn.close()


@pytest.mark.acceptance
def test_save_row_success(tmp_path: Path) -> None:
    conn, _session, employees, sessions, conversion, ids = _open(tmp_path)
    session_id, row_id = _stage_row(sessions, conn)
    before_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]

    emp_id = conversion.save_row(
        session_id=session_id,
        row_id=row_id,
        data=_employee_payload(ids),
        last_accessed_at=_T1,
    )

    assert emp_id > 0
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before_emp + 1
    assert _audit_count(conn, entity_id=emp_id) == 1
    assert sessions.list_rows(session_id) == []
    assert sessions.get_by_file_content_hash(_HASH) is None
    conn.close()


@pytest.mark.acceptance
def test_save_row_rollback_preserves_staged_row(tmp_path: Path, monkeypatch) -> None:
    conn, _session, employees, sessions, conversion, ids = _open(tmp_path)
    session_id, row_id = _stage_row(sessions, conn)
    before_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    before_audit = _audit_count(conn)

    def _boom(*_args, **_kwargs) -> None:
        raise RuntimeError("touch failed")

    monkeypatch.setattr(sessions, "touch_session", _boom)

    with pytest.raises(RuntimeError, match="touch failed"):
        conversion.save_row(
            session_id=session_id,
            row_id=row_id,
            data=_employee_payload(ids),
            last_accessed_at=_T1,
        )

    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before_emp
    assert _audit_count(conn) == before_audit
    rows = sessions.list_rows(session_id)
    assert len(rows) == 1
    assert rows[0].id == row_id
    assert sessions.get_by_file_content_hash(_HASH) is not None
    conn.close()


@pytest.mark.acceptance
def test_skip_row_success(tmp_path: Path) -> None:
    conn, _session, employees, sessions, conversion, ids = _open(tmp_path)
    session_id, row_id = _stage_row(sessions, conn)
    before_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    before_audit = _audit_count(conn)

    conversion.skip_row(session_id=session_id, row_id=row_id, last_accessed_at=_T1)

    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before_emp
    assert _audit_count(conn) == before_audit
    assert sessions.list_rows(session_id) == []
    assert sessions.get_by_file_content_hash(_HASH) is None
    conn.close()


@pytest.mark.acceptance
def test_skip_row_rollback_preserves_staged_row(tmp_path: Path, monkeypatch) -> None:
    conn, _session, employees, sessions, conversion, ids = _open(tmp_path)
    session_id, row_id = _stage_row(sessions, conn)

    def _boom(*_args, **_kwargs) -> None:
        raise RuntimeError("touch failed")

    monkeypatch.setattr(sessions, "touch_session", _boom)

    with pytest.raises(RuntimeError, match="touch failed"):
        conversion.skip_row(session_id=session_id, row_id=row_id, last_accessed_at=_T1)

    rows = sessions.list_rows(session_id)
    assert len(rows) == 1
    assert rows[0].id == row_id
    conn.close()


@pytest.mark.acceptance
def test_save_one_row_keeps_session_with_remaining_pending(tmp_path: Path) -> None:
    conn, _session, employees, sessions, conversion, ids = _open(tmp_path)
    session_id = sessions.create_session(file_content_hash=_HASH, last_accessed_at=_T0)
    first_row = sessions.insert_row(
        session_id=session_id, source_row_number=2, values_json=_JSON
    )
    second_row = sessions.insert_row(
        session_id=session_id, source_row_number=5, values_json=_JSON
    )
    conn.commit()

    conversion.save_row(
        session_id=session_id,
        row_id=first_row,
        data=_employee_payload(ids, full_name="Первый"),
        last_accessed_at=_T1,
    )

    remaining = sessions.list_rows(session_id)
    assert len(remaining) == 1
    assert remaining[0].id == second_row
    assert sessions.get_by_file_content_hash(_HASH) is not None
    conn.close()
