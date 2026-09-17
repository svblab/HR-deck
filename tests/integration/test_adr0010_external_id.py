"""ADR-0010 Part 2: stable external_id for directory entities and employees."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from data.db import Connection, connect, create_database, generate_master_key
from data.migrations import apply_pending_migrations, current_version, default_migrations_dir
from domain.employee import EmployeeCreateInput
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeService

_NOW = "2026-08-01T10:00:00Z"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_EXTERNAL_ID_TABLES = (
    "branches",
    "departments",
    "divisions",
    "positions",
    "employees",
)


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target


def _seed_post_0013_directory_rows(conn: Connection) -> None:
    conn.execute(
        "INSERT INTO branches (id, name, is_archived, created_at, updated_at) VALUES"
        " (1, 'Филиал A', 0, ?, ?),"
        " (2, 'Филиал B', 0, ?, ?)",
        (_NOW, _NOW, _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO departments (id, branch_id, name, is_archived, created_at, updated_at)"
        " VALUES"
        " (1, 1, 'Департамент A1', 0, ?, ?),"
        " (2, 2, 'Департамент B1', 0, ?, ?)",
        (_NOW, _NOW, _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO divisions ("
        " id, branch_id, department_id, name, is_archived, created_at, updated_at"
        ") VALUES"
        " (1, 1, 1, 'Отдел A1', 0, ?, ?),"
        " (2, 2, NULL, 'Отдел филиала B', 0, ?, ?)",
        (_NOW, _NOW, _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO positions ("
        " id, branch_id, name, department_required, division_required,"
        " is_archived, created_at, updated_at"
        ") VALUES"
        " (1, 1, 'Инженер A', 0, 0, 0, ?, ?),"
        " (2, 2, 'Инженер B', 0, 0, 0, ?, ?)",
        (_NOW, _NOW, _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO employees ("
        " id, full_name, position_id, branch_id, department_id, division_id,"
        " employment_type_id, note, hire_date, contacts, home_address,"
        " social_insurance_number, is_archived, created_at, updated_at"
        ") VALUES"
        " (1, 'Иванов Иван', 1, 1, 1, 1, 1, NULL, NULL, NULL, NULL, NULL, 0, ?, ?),"
        " (2, 'Петров Пётр', 2, 2, NULL, 2, 1, NULL, NULL, NULL, NULL, NULL, 0, ?, ?)",
        (_NOW, _NOW, _NOW, _NOW),
    )
    conn.commit()


def _assert_external_ids(conn: Connection, table: str) -> list[str]:
    rows = conn.execute(f"SELECT external_id FROM {table} ORDER BY id").fetchall()
    assert rows, f"{table} expected seeded rows"
    ids = [str(r[0]) for r in rows]
    for value in ids:
        assert value is not None
        assert len(value) == 36
        assert _UUID_RE.fullmatch(value), value
    assert len(set(ids)) == len(ids)
    return ids


def _open_db(tmp_path: Path) -> tuple[Connection, object]:
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: _NOW).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


@pytest.mark.acceptance
def test_adr0010_migration_backfills_external_id_on_nonempty_db(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v13 = _migrations_through(13, tmp_path / "v13")
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v13) == list(range(1, 14))
    _seed_post_0013_directory_rows(conn)
    conn.close()

    conn2 = connect(path, key)
    applied = apply_pending_migrations(conn2)
    assert applied == [14, 15]
    assert current_version(conn2) == 15

    all_ids: list[str] = []
    for table in _EXTERNAL_ID_TABLES:
        all_ids.extend(_assert_external_ids(conn2, table))
    assert len(set(all_ids)) == len(all_ids)
    assert conn2.execute("PRAGMA foreign_key_check").fetchall() == []
    conn2.close()


@pytest.mark.acceptance
def test_adr0010_create_branch_generates_external_id(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = directories.create_branch("Филиал Новый")
    from data.directories import BranchRepository

    record = BranchRepository(conn).get(branch_id)
    assert record is not None
    assert _UUID_RE.fullmatch(record.external_id)
    conn.close()


@pytest.mark.acceptance
def test_adr0010_create_department_generates_external_id(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = directories.create_branch("Филиал")
    dept_id = directories.create_department(branch_id, "Департамент")
    from data.directories import DepartmentRepository

    record = DepartmentRepository(conn).get(dept_id)
    assert record is not None
    assert _UUID_RE.fullmatch(record.external_id)
    conn.close()


@pytest.mark.acceptance
def test_adr0010_create_division_generates_external_id(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = directories.create_branch("Филиал")
    div_id = directories.create_division(branch_id, None, "Отдел филиала")
    from data.directories import DivisionRepository

    record = DivisionRepository(conn).get(div_id)
    assert record is not None
    assert _UUID_RE.fullmatch(record.external_id)
    conn.close()


@pytest.mark.acceptance
def test_adr0010_create_position_generates_external_id(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _NOW)
    branch_id = directories.create_branch("Филиал")
    pos_id = directories.create_position(branch_id, "Инженер")
    record = directories.get_position(pos_id)
    assert record is not None
    assert _UUID_RE.fullmatch(record.external_id)
    conn.close()


@pytest.mark.acceptance
def test_adr0010_create_employee_generates_external_id(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _NOW)
    employees = EmployeeService(conn, session, clock=lambda: _NOW)
    branch_id = directories.create_branch("Филиал")
    pos_id = directories.create_position(branch_id, "Инженер")
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Сидоров Сидор",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=None,
            division_id=None,
            employment_type_id=1,
        )
    )
    from data.employees import EmployeeRepository

    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    assert _UUID_RE.fullmatch(record.external_id)
    conn.close()


@pytest.mark.acceptance
def test_adr0010_external_id_unique_across_rows(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _NOW)
    employees = EmployeeService(conn, session, clock=lambda: _NOW)

    branch_a = directories.create_branch("Филиал A")
    branch_b = directories.create_branch("Филиал B")
    dept_a = directories.create_department(branch_a, "Департамент A")
    dept_b = directories.create_department(branch_b, "Департамент B")
    div_a = directories.create_division(branch_a, dept_a, "Отдел A")
    div_b = directories.create_division(branch_b, dept_b, "Отдел B")
    pos_a = directories.create_position(branch_a, "Должность A")
    pos_b = directories.create_position(branch_b, "Должность B")
    emp_a = employees.create_employee(
        EmployeeCreateInput(
            full_name="Сотрудник A",
            position_id=pos_a,
            branch_id=branch_a,
            department_id=dept_a,
            division_id=div_a,
            employment_type_id=1,
        )
    )
    emp_b = employees.create_employee(
        EmployeeCreateInput(
            full_name="Сотрудник B",
            position_id=pos_b,
            branch_id=branch_b,
            department_id=dept_b,
            division_id=div_b,
            employment_type_id=1,
        )
    )

    from data.directories import (
        BranchRepository,
        DepartmentRepository,
        DivisionRepository,
        PositionRepository,
    )
    from data.employees import EmployeeRepository

    ids = [
        BranchRepository(conn).get(branch_a).external_id,  # type: ignore[union-attr]
        BranchRepository(conn).get(branch_b).external_id,  # type: ignore[union-attr]
        DepartmentRepository(conn).get(dept_a).external_id,  # type: ignore[union-attr]
        DepartmentRepository(conn).get(dept_b).external_id,  # type: ignore[union-attr]
        DivisionRepository(conn).get(div_a).external_id,  # type: ignore[union-attr]
        DivisionRepository(conn).get(div_b).external_id,  # type: ignore[union-attr]
        PositionRepository(conn).get(pos_a).external_id,  # type: ignore[union-attr]
        PositionRepository(conn).get(pos_b).external_id,  # type: ignore[union-attr]
        EmployeeRepository(conn).get(emp_a).external_id,  # type: ignore[union-attr]
        EmployeeRepository(conn).get(emp_b).external_id,  # type: ignore[union-attr]
    ]
    assert all(_UUID_RE.fullmatch(value) for value in ids)
    assert len(set(ids)) == len(ids)
    conn.close()
