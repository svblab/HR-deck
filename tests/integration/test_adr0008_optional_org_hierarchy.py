"""ADR-0008 Phase 0: optional org hierarchy migrations and domain rules."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import Connection, connect, create_database, generate_master_key
from data.employees import EmployeeRepository
from data.migrations import apply_pending_migrations, current_version, default_migrations_dir
from domain.employee import EmployeeValidationError, validate_employee_org
from domain.org_structure import DepartmentRef, DivisionRef
from services.bootstrap import BootstrapService
from services.directories import DirectoryError, DirectoryService
from services.employee_import import EmployeeImportService
from services.employees import EmployeeService
from services.session import SessionState

_NOW = "2026-08-01T10:00:00Z"


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target


def _seed_pre_0010_org(conn: Connection) -> dict[str, int]:
    conn.execute(
        "INSERT INTO branches (id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 'Филиал Север', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO departments (id, branch_id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 1, 'Департамент разработки', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO divisions (id, department_id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 1, 'Отдел платформы', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO positions (id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 'Инженер', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO employees ("
        " id, full_name, position_id, branch_id, department_id, division_id,"
        " employment_type_id, is_archived, created_at, updated_at"
        ") VALUES (1, 'Иванов Иван', 1, 1, 1, 1, 1, 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.commit()
    return {
        "branch_id": 1,
        "department_id": 1,
        "division_id": 1,
        "employee_id": 1,
    }


def _fk_check_clean(conn: Connection) -> None:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert rows == []


def _open_db(tmp_path: Path) -> tuple[Connection, SessionState]:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: _NOW)
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


@pytest.mark.acceptance
def test_adr0008_migration_divisions_backfill_branch_id_on_nonempty_db(
    tmp_path: Path,
) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v9 = _migrations_through(9, tmp_path / "v9")
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v9) == list(range(1, 10))
    ids = _seed_pre_0010_org(conn)
    div_count = conn.execute("SELECT COUNT(*) FROM divisions").fetchone()[0]
    conn.close()

    conn2 = connect(path, key)
    mig_v10 = _migrations_through(10, tmp_path / "v10")
    applied = apply_pending_migrations(conn2, migrations_dir=mig_v10)
    assert applied == [10]
    assert current_version(conn2) == 10
    row = conn2.execute(
        "SELECT branch_id, department_id FROM divisions WHERE id = ?",
        (ids["division_id"],),
    ).fetchone()
    assert row == (ids["branch_id"], ids["department_id"])
    assert conn2.execute("SELECT COUNT(*) FROM divisions").fetchone()[0] == div_count
    _fk_check_clean(conn2)
    conn2.close()


@pytest.mark.acceptance
def test_adr0008_division_name_unique_within_branch_regardless_of_department(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = svc.create_branch("Филиал Альфа")
    dept_id = svc.create_department(branch_id, "Департамент A")
    svc.create_division(branch_id, dept_id, "Секретариат")
    with pytest.raises(sqlcipher.IntegrityError):
        svc.create_division(branch_id, None, "Секретариат")
    conn.close()


@pytest.mark.acceptance
def test_adr0008_migration_employees_allows_null_department_on_nonempty_db(
    tmp_path: Path,
) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v9 = _migrations_through(9, tmp_path / "v9b")
    conn = create_database(path, key)
    apply_pending_migrations(conn, migrations_dir=mig_v9)
    _seed_pre_0010_org(conn)
    emp_count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    conn.close()

    conn2 = connect(path, key)
    applied = apply_pending_migrations(conn2)
    assert applied == [10, 11]
    assert current_version(conn2) == 11
    assert conn2.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == emp_count
    conn2.execute(
        "UPDATE employees SET department_id = NULL, division_id = NULL WHERE id = 1"
    )
    conn2.commit()
    row = conn2.execute(
        "SELECT department_id, division_id FROM employees WHERE id = 1"
    ).fetchone()
    assert row == (None, None)
    _fk_check_clean(conn2)
    conn2.close()


@pytest.mark.acceptance
def test_adr0008_migration_employees_with_status_history_on_nonempty_db(
    tmp_path: Path,
) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v9 = _migrations_through(9, tmp_path / "v9-status")
    conn = create_database(path, key)
    apply_pending_migrations(conn, migrations_dir=mig_v9)
    ids = _seed_pre_0010_org(conn)
    conn.execute(
        "INSERT INTO status_history ("
        " employee_id, status_id, start_date, end_date, note, created_at"
        ") VALUES (?, 1, '2026-08-01', '2026-08-10', 'adr0008 fixture', ?)",
        (ids["employee_id"], _NOW),
    )
    conn.commit()
    expected = conn.execute(
        "SELECT employee_id, status_id, start_date, end_date, note, created_at, "
        "created_by_account_id FROM status_history WHERE employee_id = ?",
        (ids["employee_id"],),
    ).fetchone()
    conn.close()

    conn2 = connect(path, key)
    applied = apply_pending_migrations(conn2)
    assert applied == [10, 11]
    assert current_version(conn2) == 11
    restored = conn2.execute(
        "SELECT employee_id, status_id, start_date, end_date, note, created_at, "
        "created_by_account_id FROM status_history WHERE employee_id = ?",
        (ids["employee_id"],),
    ).fetchone()
    assert restored == expected
    _fk_check_clean(conn2)
    with pytest.raises(sqlcipher.IntegrityError, match="DELETE forbidden"):
        conn2.execute("DELETE FROM status_history WHERE employee_id = ?", (ids["employee_id"],))
    with pytest.raises(sqlcipher.IntegrityError, match="UPDATE forbidden"):
        conn2.execute(
            "UPDATE status_history SET note = 'x' WHERE employee_id = ?",
            (ids["employee_id"],),
        )
    conn2.close()


@pytest.mark.acceptance
def test_adr0008_create_division_directly_under_branch(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = svc.create_branch("Филиал Центр")
    div_id = svc.create_division(branch_id, None, "Секретариат")
    row = conn.execute(
        "SELECT branch_id, department_id FROM divisions WHERE id = ?",
        (div_id,),
    ).fetchone()
    assert row == (branch_id, None)
    conn.close()


@pytest.mark.acceptance
def test_adr0008_division_department_must_belong_to_branch_when_present(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_a = svc.create_branch("Филиал A")
    branch_b = svc.create_branch("Филиал B")
    dept_b = svc.create_department(branch_b, "Департамент B")
    with pytest.raises(DirectoryError, match="department does not belong to branch"):
        svc.create_division(branch_a, dept_b, "Отдел X")
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute(
            "INSERT INTO divisions ("
            " branch_id, department_id, name, is_archived, created_at, updated_at"
            ") "
            "VALUES (?, ?, 'Отдел Y', 0, ?, ?)",
            (branch_a, dept_b, _NOW, _NOW),
        )
    conn.close()


@pytest.mark.acceptance
def test_adr0008_cannot_rebranch_division_referenced_by_employees(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_a = svc.create_branch("Филиал A")
    branch_b = svc.create_branch("Филиал B")
    div_id = svc.create_division(branch_a, None, "Секретариат")
    pos_id = svc.create_position("Сотрудник")
    et_id = svc.list_employment_types(active_only=True)[0].id
    repo = EmployeeRepository(conn)
    repo.create(
        full_name="Директор",
        position_id=pos_id,
        branch_id=branch_a,
        department_id=None,
        employment_type_id=et_id,
        division_id=div_id,
        created_at=_NOW,
    )
    conn.commit()
    with pytest.raises(sqlcipher.DatabaseError, match="cannot move division"):
        conn.execute(
            "UPDATE divisions SET branch_id = ? WHERE id = ?",
            (branch_b, div_id),
        )
    conn.close()


@pytest.mark.acceptance
def test_adr0008_create_employee_branch_only(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = svc.create_branch("Филиал A")
    pos_id = svc.create_position("Директор")
    et_id = svc.list_employment_types(active_only=True)[0].id
    validate_employee_org(
        branch_id=branch_id,
        department_id=None,
        division_id=None,
        department=None,
        division=None,
    )
    repo = EmployeeRepository(conn)
    emp_id = repo.create(
        full_name="Директор филиала",
        position_id=pos_id,
        branch_id=branch_id,
        department_id=None,
        employment_type_id=et_id,
        created_at=_NOW,
    )
    conn.commit()
    row = conn.execute(
        "SELECT branch_id, department_id, division_id FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert row == (branch_id, None, None)
    conn.close()


@pytest.mark.acceptance
def test_adr0008_create_employee_in_branch_direct_division(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = svc.create_branch("Филиал A")
    pos_id = svc.create_position("Секретарь")
    et_id = svc.list_employment_types(active_only=True)[0].id
    div_id = svc.create_division(branch_id, None, "Секретариат")
    div_row = conn.execute(
        "SELECT id, branch_id, department_id FROM divisions WHERE id = ?",
        (div_id,),
    ).fetchone()
    assert div_row is not None
    validate_employee_org(
        branch_id=branch_id,
        department_id=None,
        division_id=div_id,
        department=None,
        division=DivisionRef(
            id=int(div_row[0]),
            branch_id=int(div_row[1]),
            department_id=int(div_row[2]) if div_row[2] is not None else None,
        ),
    )
    repo = EmployeeRepository(conn)
    emp_id = repo.create(
        full_name="Секретарь",
        position_id=pos_id,
        branch_id=branch_id,
        department_id=None,
        employment_type_id=et_id,
        division_id=div_id,
        created_at=_NOW,
    )
    conn.commit()
    row = conn.execute(
        "SELECT department_id, division_id FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert row == (None, div_id)
    conn.close()


@pytest.mark.acceptance
def test_adr0008_employee_department_must_exactly_match_division_department_including_null(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = svc.create_branch("Филиал A")
    dept_id = svc.create_department(branch_id, "Департамент A")
    div_branch = svc.create_division(branch_id, None, "Секретариат")
    div_dept = svc.create_division(branch_id, dept_id, "Отдел A")

    with pytest.raises(EmployeeValidationError):
        validate_employee_org(
            branch_id=branch_id,
            department_id=dept_id,
            division_id=div_branch,
            department=DepartmentRef(id=dept_id, branch_id=branch_id),
            division=DivisionRef(id=div_branch, branch_id=branch_id, department_id=None),
        )

    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute(
            "INSERT INTO employees ("
            " full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, is_archived, created_at, updated_at"
            ") VALUES ('X', 1, ?, ?, ?, 1, 0, ?, ?)",
            (branch_id, dept_id, div_branch, _NOW, _NOW),
        )

    with pytest.raises(EmployeeValidationError):
        validate_employee_org(
            branch_id=branch_id,
            department_id=None,
            division_id=div_dept,
            department=None,
            division=DivisionRef(id=div_dept, branch_id=branch_id, department_id=dept_id),
        )

    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute(
            "INSERT INTO employees ("
            " full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, is_archived, created_at, updated_at"
            ") VALUES ('Y', 1, ?, NULL, ?, 1, 0, ?, ?)",
            (branch_id, div_dept, _NOW, _NOW),
        )
    conn.close()


@pytest.mark.acceptance
def test_adr0008_import_empty_department_nonempty_division_matches_branch_division(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = svc.create_branch("Филиал A")
    svc.create_division(branch_id, None, "Секретариат")
    pos_id = svc.create_position("Секретарь")
    et_name = svc.list_employment_types(active_only=True)[0].name
    employees = EmployeeService(conn, session, clock=lambda: _NOW)
    importer = EmployeeImportService(employees, svc, session)
    preview = importer.preview_rows(
        [
            "ФИО",
            "Должность",
            "Филиал",
            "Департамент",
            "Отдел",
            "Тип занятости",
        ],
        [
            [
                "Секретарь импорт",
                "Секретарь",
                "Филиал A",
                "",
                "Секретариат",
                et_name,
            ]
        ],
    )
    assert not preview.errors
    assert len(preview.ready) == 1
    payload = preview.ready[0].payload
    assert payload.department_id is None
    assert payload.division_id is not None
    assert payload.position_id == pos_id
    conn.close()


@pytest.mark.acceptance
def test_adr0008_import_empty_department_unknown_division_name_errors(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    svc.create_branch("Филиал A")
    svc.create_position("Секретарь")
    et_name = svc.list_employment_types(active_only=True)[0].name
    employees = EmployeeService(conn, session, clock=lambda: _NOW)
    importer = EmployeeImportService(employees, svc, session)
    preview = importer.preview_rows(
        [
            "ФИО",
            "Должность",
            "Филиал",
            "Департамент",
            "Отдел",
            "Тип занятости",
        ],
        [
            [
                "Секретарь импорт",
                "Секретарь",
                "Филиал A",
                "",
                "Нет такого отдела",
                et_name,
            ]
        ],
    )
    assert not preview.ready
    assert any("unknown division" in issue.message for issue in preview.errors)
    conn.close()


@pytest.mark.acceptance
def test_adr0008_import_both_department_and_division_empty_is_valid(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    svc = DirectoryService(conn, session, clock=lambda: _NOW)
    svc.create_branch("Филиал A")
    svc.create_position("Директор")
    et_name = svc.list_employment_types(active_only=True)[0].name
    employees = EmployeeService(conn, session, clock=lambda: _NOW)
    importer = EmployeeImportService(employees, svc, session)
    preview = importer.preview_rows(
        [
            "ФИО",
            "Должность",
            "Филиал",
            "Департамент",
            "Отдел",
            "Тип занятости",
        ],
        [
            [
                "Директор филиала",
                "Директор",
                "Филиал A",
                "",
                "",
                et_name,
            ]
        ],
    )
    assert not preview.errors
    assert len(preview.ready) == 1
    payload = preview.ready[0].payload
    assert payload.department_id is None
    assert payload.division_id is None
    conn.close()
