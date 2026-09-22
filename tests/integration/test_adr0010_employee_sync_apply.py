"""ADR-0010 Part 4b: apply employee rows from directory sync packages."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from data.directories import (
    BranchRepository,
    DepartmentRepository,
    DivisionRepository,
    PositionRepository,
)
from data.employees import EmployeeRepository
from domain.directory_sync import DirectorySyncPackage
from domain.employee import EmployeeCreateInput
from domain.employee_reconciliation import EmployeeSyncApplyError, EmployeeSyncConflictError
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.directory_sync_import import DirectorySyncImportService
from services.employee_sync_import import EmployeeSyncImportService
from services.employees import EmployeeService
from services.status_history import StatusHistoryService

_T0 = "2026-09-18T10:00:00Z"
_T1 = "2026-09-18T11:00:00Z"


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
    sync = EmployeeSyncImportService(conn, session, clock=lambda: clock)
    importer = DirectorySyncImportService(conn, session, clock=lambda: clock)
    return directories, employees, sync, importer


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


def _org_external_ids(conn, org: dict[str, int]) -> tuple[str, str, str, str]:
    branch = BranchRepository(conn).get(org["branch_id"])
    dept = DepartmentRepository(conn).get(org["department_id"])
    div = DivisionRepository(conn).get(org["division_id"])
    pos = PositionRepository(conn).get(org["position_id"])
    assert branch and dept and div and pos
    return branch.external_id, dept.external_id, div.external_id, pos.external_id


def _employee_row(
    conn,
    org: dict[str, int],
    *,
    external_id: str,
    full_name: str,
    note: str | None = None,
    is_archived: bool = False,
) -> dict[str, object]:
    branch_ext, dept_ext, div_ext, pos_ext = _org_external_ids(conn, org)
    return {
        "id": 9001,
        "external_id": external_id,
        "full_name": full_name,
        "position_external_id": pos_ext,
        "branch_external_id": branch_ext,
        "department_external_id": dept_ext,
        "division_external_id": div_ext,
        "employment_type_id": 1,
        "note": note,
        "hire_date": None,
        "contacts": None,
        "home_address": None,
        "social_insurance_number": None,
        "needs_org_review": False,
        "is_archived": is_archived,
        "created_at": _T0,
        "updated_at": _T0,
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


def _count_employees(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0])


@pytest.mark.acceptance
def test_adr0010_apply_creates_new_employee_by_external_id(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, _employees, sync, _importer = _services(conn, session)
    org = _seed_org(directories)
    new_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=new_ext,
                    full_name="Кузнецов Кузьма Кузьмич",
                )
            ]
        }
    )
    sync.apply_employees(package)
    record = EmployeeRepository(conn).get_by_external_id(new_ext)
    assert record is not None
    assert record.full_name == "Кузнецов Кузьма Кузьмич"
    assert record.position_id == org["position_id"]
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_updates_existing_employee_matched_by_external_id(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, sync, _importer = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=record.external_id,
                    full_name="Иванов Иван Иванович",
                    note="из пакета",
                )
            ]
        }
    )
    sync.apply_employees(package)
    updated = EmployeeRepository(conn).get(emp_id)
    assert updated is not None
    assert updated.note == "из пакета"
    assert _count_employees(conn) == 1
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_rejects_external_id_name_conflict(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, employees, sync, _importer = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=record.external_id,
                    full_name="Петров Пётр Петрович",
                )
            ]
        }
    )
    with pytest.raises(EmployeeSyncConflictError) as exc_info:
        sync.apply_employees(package)
    assert exc_info.value.details[0].status.value == "conflict"
    assert EmployeeRepository(conn).get(emp_id).full_name == "Иванов Иван Иванович"
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_rejects_missing_directory_reference(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, _employees, sync, _importer = _services(conn, session)
    org = _seed_org(directories)
    row = _employee_row(
        conn,
        org,
        external_id=str(uuid.uuid4()),
        full_name="Новый Сотрудник",
    )
    row["position_external_id"] = str(uuid.uuid4())
    package = DirectorySyncPackage(tables={"employees": [row]})
    with pytest.raises(EmployeeSyncApplyError):
        sync.apply_employees(package)
    assert _count_employees(conn) == 0
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_rejects_invalid_org_invariant(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, _employees, sync, _importer = _services(conn, session)
    branch_a = directories.create_branch("Филиал A")
    branch_b = directories.create_branch("Филиал B")
    dept_b = directories.create_department(branch_b, "Департамент B")
    pos_a = directories.create_position(branch_a, "Инженер A")
    branch_a_ext = BranchRepository(conn).get(branch_a).external_id
    dept_b_ext = DepartmentRepository(conn).get(dept_b).external_id
    pos_a_ext = PositionRepository(conn).get(pos_a).external_id
    package = DirectorySyncPackage(
        tables={
            "employees": [
                {
                    "id": 1,
                    "external_id": str(uuid.uuid4()),
                    "full_name": "Ошибка Инварианта",
                    "position_external_id": pos_a_ext,
                    "branch_external_id": branch_a_ext,
                    "department_external_id": dept_b_ext,
                    "division_external_id": None,
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
            ]
        }
    )
    with pytest.raises(EmployeeSyncApplyError):
        sync.apply_employees(package)
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_conflict_does_not_partially_apply_other_rows(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, employees, sync, _importer = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    good_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=good_ext,
                    full_name="Новый Успешный",
                ),
                _employee_row(
                    conn,
                    org,
                    external_id=record.external_id,
                    full_name="Другое Имя",
                ),
            ]
        }
    )
    with pytest.raises(EmployeeSyncConflictError):
        sync.apply_employees(package)
    assert EmployeeRepository(conn).get_by_external_id(good_ext) is None
    assert _count_employees(conn) == 1
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_is_idempotent(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, employees, sync, _importer = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=record.external_id,
                    full_name="Иванов Иван Иванович",
                )
            ]
        }
    )
    sync.apply_employees(package)
    sync.apply_employees(package)
    assert _count_employees(conn) == 1
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_empty_employee_table_is_noop(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, employees, sync, _importer = _services(conn, session)
    org = _seed_org(directories)
    _create_employee(employees, org, full_name="Иванов Иван Иванович")
    before = _count_employees(conn)
    sync.apply_employees(DirectorySyncPackage(tables={}))
    assert _count_employees(conn) == before
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_preserves_status_history_on_update(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, employees, sync, _importer = _services(conn, session)
    history = StatusHistoryService(conn, session, clock=lambda: _T0)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    history.assign_status(emp_id, status_id=1, start_date="2026-01-01", confirmed=True)
    before = conn.execute(
        "SELECT COUNT(*) FROM status_history WHERE employee_id = ?", (emp_id,)
    ).fetchone()[0]
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=record.external_id,
                    full_name="Иванов Иван Иванович",
                    note="обновление",
                )
            ]
        }
    )
    sync.apply_employees(package)
    after = conn.execute(
        "SELECT COUNT(*) FROM status_history WHERE employee_id = ?", (emp_id,)
    ).fetchone()[0]
    assert before == after == 1
    conn.close()


@pytest.mark.acceptance
def test_adr0010_full_package_apply_directories_then_employees(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, employees, _sync, importer = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    branch_ext, dept_ext, div_ext, pos_ext = _org_external_ids(conn, org)
    package = DirectorySyncPackage(
        tables={
            "branches": [
                {
                    "id": 1,
                    "external_id": branch_ext,
                    "name": "Филиал Центр",
                    "is_archived": False,
                    "created_at": _T0,
                    "updated_at": _T0,
                }
            ],
            "departments": [
                {
                    "id": 1,
                    "external_id": dept_ext,
                    "branch_external_id": branch_ext,
                    "name": "Департамент QA",
                    "is_archived": False,
                    "created_at": _T0,
                    "updated_at": _T0,
                }
            ],
            "divisions": [
                {
                    "id": 1,
                    "external_id": div_ext,
                    "branch_external_id": branch_ext,
                    "department_external_id": dept_ext,
                    "name": "Отдел A",
                    "is_archived": False,
                    "created_at": _T0,
                    "updated_at": _T0,
                }
            ],
            "positions": [
                {
                    "id": 1,
                    "external_id": pos_ext,
                    "branch_external_id": branch_ext,
                    "name": "Инженер",
                    "department_required": False,
                    "division_required": False,
                    "is_archived": False,
                    "created_at": _T0,
                    "updated_at": _T0,
                }
            ],
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=record.external_id,
                    full_name="Иванов Иван Иванович",
                    note="после справочников",
                )
            ],
        }
    )
    importer.apply_package(package)
    updated = EmployeeRepository(conn).get(emp_id)
    assert updated is not None
    assert updated.note == "после справочников"
    conn.close()


@pytest.mark.acceptance
def test_adr0010_full_package_rolls_back_directories_on_employee_conflict(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, _sync, importer = _services(conn, session)
    org = _seed_org(directories)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    branch_ext, dept_ext, div_ext, pos_ext = _org_external_ids(conn, org)
    package = DirectorySyncPackage(
        tables={
            "branches": [
                {
                    "id": 1,
                    "external_id": branch_ext,
                    "name": "Филиал Переименованный",
                    "is_archived": False,
                    "created_at": _T0,
                    "updated_at": _T0,
                }
            ],
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=record.external_id,
                    full_name="Конфликт Имени",
                )
            ],
        }
    )
    with pytest.raises(EmployeeSyncConflictError):
        importer.apply_package(package)
    branch = BranchRepository(conn).get(org["branch_id"])
    assert branch is not None
    assert branch.name == "Филиал Центр"
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_rejects_low_confidence_name_match_without_external_id(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, sync, _importer = _services(conn, session)
    org = _seed_org(directories)
    _create_employee(employees, org, full_name="Сидоров Сидор Сидорович")
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=str(uuid.uuid4()),
                    full_name="Сидоров Сидор Сидорович",
                )
            ]
        }
    )
    with pytest.raises(EmployeeSyncConflictError) as exc_info:
        sync.apply_employees(package)
    assert exc_info.value.details[0].status.value == "low"
    assert _count_employees(conn) == 1
    conn.close()
