"""ADR-0010 Part 4b step 1: read-only employee reconciliation matching."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from data.directories import DepartmentRepository, DivisionRepository
from data.employees import EmployeeRepository
from domain.directory_sync import DirectorySyncPackage
from domain.employee import EmployeeCreateInput
from domain.employee_reconciliation import EmployeeMatchStatus
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employee_reconciliation import EmployeeReconciliationService
from services.employees import EmployeeService

_T0 = "2026-09-18T10:00:00Z"


def _open(tmp_path: Path, *, clock: str = _T0):
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: clock).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


def _services(conn, session, *, clock: str = _T0):
    directories = DirectoryService(conn, session, clock=lambda: clock)
    employees = EmployeeService(conn, session, clock=lambda: clock)
    recon = EmployeeReconciliationService(conn, session)
    return directories, employees, recon


def _seed_org(directories: DirectoryService) -> dict[str, int]:
    branch_id = directories.create_branch("Филиал Центр")
    dept_id = directories.create_department(branch_id, "Департамент QA")
    div_id = directories.create_division(branch_id, dept_id, "Отдел A")
    pos_id = directories.create_position(branch_id, "Инженер")
    return {
        "branch_id": branch_id,
        "department_id": dept_id,
        "division_id": div_id,
        "position_id": pos_id,
    }


def _create_employee(
    employees: EmployeeService,
    org: dict[str, int],
    *,
    full_name: str,
) -> int:
    return employees.create_employee(
        EmployeeCreateInput(
            full_name=full_name,
            position_id=org["position_id"],
            branch_id=org["branch_id"],
            department_id=org["department_id"],
            division_id=org["division_id"],
            employment_type_id=1,
        )
    )


def _org_external_ids(conn, org: dict[str, int]) -> tuple[str, str]:
    dept = DepartmentRepository(conn).get(org["department_id"])
    div = DivisionRepository(conn).get(org["division_id"])
    assert dept is not None and div is not None
    return dept.external_id, div.external_id


def _package_employee_row(
    *,
    external_id: str,
    full_name: str,
    department_external_id: str | None,
    division_external_id: str | None,
) -> dict[str, object]:
    return {
        "id": 9001,
        "external_id": external_id,
        "full_name": full_name,
        "position_external_id": str(uuid.uuid4()),
        "branch_external_id": str(uuid.uuid4()),
        "department_external_id": department_external_id,
        "division_external_id": division_external_id,
        "employment_type_id": 1,
        "note": None,
        "hire_date": None,
        "contacts": None,
        "home_address": None,
        "social_insurance_number": None,
        "needs_org_review": False,
        "is_archived": False,
        "created_at": _T0,
        "updated_at": _T0,
    }


def _dump_all_tables(conn) -> dict[str, list[tuple]]:
    names = [
        str(r[0])
        for r in conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            " ORDER BY name"
        ).fetchall()
    ]
    return {
        name: list(conn.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall())
        for name in names
    }


@pytest.mark.acceptance
def test_adr0010_reconciliation_exact_match_when_external_id_and_name_agree(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, recon = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    dept_ext, div_ext = _org_external_ids(conn, org)
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _package_employee_row(
                    external_id=record.external_id,
                    full_name="Иванов Иван Иванович",
                    department_external_id=dept_ext,
                    division_external_id=div_ext,
                )
            ]
        }
    )
    result = recon.build_reconciliation(package)
    assert len(result) == 1
    assert result[0].status == EmployeeMatchStatus.EXACT
    assert result[0].matched_employee_id == emp_id
    assert result[0].candidate_employee_ids == ()
    conn.close()


@pytest.mark.acceptance
def test_adr0010_reconciliation_conflict_when_external_id_matches_but_name_differs(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, recon = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    dept_ext, div_ext = _org_external_ids(conn, org)
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _package_employee_row(
                    external_id=record.external_id,
                    full_name="Петров Пётр Петрович",
                    department_external_id=dept_ext,
                    division_external_id=div_ext,
                )
            ]
        }
    )
    result = recon.build_reconciliation(package)
    assert len(result) == 1
    assert result[0].status == EmployeeMatchStatus.CONFLICT
    assert result[0].matched_employee_id == emp_id
    conn.close()


@pytest.mark.acceptance
def test_adr0010_reconciliation_low_confidence_single_name_candidate(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, recon = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Сидоров Сидор Сидорович")
    dept_ext, div_ext = _org_external_ids(conn, org)
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _package_employee_row(
                    external_id=str(uuid.uuid4()),
                    full_name="Сидоров Сидор Сидорович",
                    department_external_id=dept_ext,
                    division_external_id=div_ext,
                )
            ]
        }
    )
    result = recon.build_reconciliation(package)
    assert len(result) == 1
    assert result[0].status == EmployeeMatchStatus.LOW
    assert result[0].matched_employee_id == emp_id
    assert result[0].candidate_employee_ids == ()
    conn.close()


@pytest.mark.acceptance
def test_adr0010_reconciliation_ambiguous_multiple_name_candidates(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, recon = _services(conn, session)
    org = _seed_org(directories)
    first = _create_employee(employees, org, full_name="Новиков Николай Николаевич")
    second = _create_employee(employees, org, full_name="Новиков Николай Николаевич")
    dept_ext, div_ext = _org_external_ids(conn, org)
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _package_employee_row(
                    external_id=str(uuid.uuid4()),
                    full_name="Новиков Николай Николаевич",
                    department_external_id=dept_ext,
                    division_external_id=div_ext,
                )
            ]
        }
    )
    result = recon.build_reconciliation(package)
    assert len(result) == 1
    assert result[0].status == EmployeeMatchStatus.AMBIGUOUS
    assert result[0].matched_employee_id is None
    assert result[0].candidate_employee_ids == tuple(sorted((first, second)))
    conn.close()


@pytest.mark.acceptance
def test_adr0010_reconciliation_new_when_no_external_id_and_no_name_candidates(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, recon = _services(conn, session)
    org = _seed_org(directories)
    _create_employee(employees, org, full_name="Иванов Иван Иванович")
    dept_ext, div_ext = _org_external_ids(conn, org)
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _package_employee_row(
                    external_id=str(uuid.uuid4()),
                    full_name="Кузнецов Кузьма Кузьмич",
                    department_external_id=dept_ext,
                    division_external_id=div_ext,
                )
            ]
        }
    )
    result = recon.build_reconciliation(package)
    assert len(result) == 1
    assert result[0].status == EmployeeMatchStatus.NEW
    assert result[0].matched_employee_id is None
    assert result[0].candidate_employee_ids == ()
    conn.close()


@pytest.mark.acceptance
def test_adr0010_reconciliation_never_writes_to_database(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, employees, recon = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    dept_ext, div_ext = _org_external_ids(conn, org)
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _package_employee_row(
                    external_id=record.external_id,
                    full_name="Иванов Иван Иванович",
                    department_external_id=dept_ext,
                    division_external_id=div_ext,
                ),
                _package_employee_row(
                    external_id=record.external_id,
                    full_name="Другое Имя",
                    department_external_id=dept_ext,
                    division_external_id=div_ext,
                ),
                _package_employee_row(
                    external_id=str(uuid.uuid4()),
                    full_name="Иванов Иван Иванович",
                    department_external_id=dept_ext,
                    division_external_id=div_ext,
                ),
                _package_employee_row(
                    external_id=str(uuid.uuid4()),
                    full_name="Новый Сотрудник",
                    department_external_id=dept_ext,
                    division_external_id=div_ext,
                ),
            ]
        }
    )
    before = _dump_all_tables(conn)
    result = recon.build_reconciliation(package)
    after = _dump_all_tables(conn)
    assert len(result) == 4
    assert before == after
    conn.close()


@pytest.mark.acceptance
def test_adr0010_reconciliation_resolves_department_division_candidates_by_external_id_not_name_collision(  # noqa: E501
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, recon = _services(conn, session)
    branch_a = directories.create_branch("Филиал A")
    branch_b = directories.create_branch("Филиал B")
    dept_a = directories.create_department(branch_a, "Департамент IT")
    dept_b = directories.create_department(branch_b, "Департамент IT")
    div_a = directories.create_division(branch_a, dept_a, "Отдел общий")
    div_b = directories.create_division(branch_b, dept_b, "Отдел общий")
    pos_a = directories.create_position(branch_a, "Инженер")
    directories.create_position(branch_b, "Инженер")
    emp_a = employees.create_employee(
        EmployeeCreateInput(
            full_name="Козлов Кирилл Кириллович",
            position_id=pos_a,
            branch_id=branch_a,
            department_id=dept_a,
            division_id=div_a,
            employment_type_id=1,
        )
    )
    dept_b_row = DepartmentRepository(conn).get(dept_b)
    div_b_row = DivisionRepository(conn).get(div_b)
    assert dept_b_row is not None and div_b_row is not None
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _package_employee_row(
                    external_id=str(uuid.uuid4()),
                    full_name="Козлов Кирилл Кириллович",
                    department_external_id=dept_b_row.external_id,
                    division_external_id=div_b_row.external_id,
                )
            ]
        }
    )
    result = recon.build_reconciliation(package)
    assert len(result) == 1
    assert result[0].status == EmployeeMatchStatus.NEW
    assert result[0].matched_employee_id is None
    assert emp_a not in result[0].candidate_employee_ids
    conn.close()
