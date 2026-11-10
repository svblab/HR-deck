"""E1-04: CONFLICT on name or branch mismatch rejects the whole sync package."""

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
from domain.employee_reconciliation import EmployeeMatchStatus, EmployeeSyncConflictError
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employee_sync_import import EmployeeSyncImportService
from services.employees import EmployeeService

_T0 = "2026-09-18T10:00:00Z"


def _open(tmp_path: Path):
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


def _seed(conn, session):
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    sync = EmployeeSyncImportService(conn, session, clock=lambda: _T0)
    branch_id = directories.create_branch("Филиал Центр")
    dept_id = directories.create_department(branch_id, "Департамент QA")
    div_id = directories.create_division(branch_id, dept_id, "Отдел A")
    pos_id = directories.create_position(branch_id, "Инженер")
    org = {
        "branch_id": branch_id,
        "department_id": dept_id,
        "division_id": div_id,
        "position_id": pos_id,
    }
    return directories, employees, sync, org


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
    branch_external_id: str | None = None,
    note: str | None = None,
) -> dict[str, object]:
    branch_ext, dept_ext, div_ext, pos_ext = _org_external_ids(conn, org)
    return {
        "id": 9001,
        "external_id": external_id,
        "full_name": full_name,
        "position_external_id": pos_ext,
        "branch_external_id": (
            branch_external_id if branch_external_id is not None else branch_ext
        ),
        "department_external_id": dept_ext,
        "division_external_id": div_ext,
        "employment_type_id": 1,
        "note": note,
        "hire_date": None,
        "contacts": None,
        "home_address": None,
        "social_insurance_number": None,
        "needs_org_review": False,
        "is_archived": False,
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


def test_branch_mismatch_rejects_whole_package_and_writes_nothing(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, sync, org = _seed(conn, session)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    before_count = _count_employees(conn)
    before_note = record.note
    other_branch_id = directories.create_branch("Филиал Другой")
    other_branch = BranchRepository(conn).get(other_branch_id)
    assert other_branch is not None
    new_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=record.external_id,
                    full_name="Иванов Иван Иванович",
                    branch_external_id=other_branch.external_id,
                    note="must-not-apply",
                ),
                _employee_row(
                    conn,
                    org,
                    external_id=new_ext,
                    full_name="Кузнецов Кузьма Кузьмич",
                ),
            ]
        }
    )
    with pytest.raises(EmployeeSyncConflictError) as exc_info:
        sync.apply_employees(package)
    assert exc_info.value.details[0].status == EmployeeMatchStatus.CONFLICT
    assert _count_employees(conn) == before_count
    assert EmployeeRepository(conn).get_by_external_id(new_ext) is None
    unchanged = EmployeeRepository(conn).get(emp_id)
    assert unchanged is not None
    assert unchanged.note == before_note
    assert unchanged.full_name == "Иванов Иван Иванович"
    conn.close()


def test_exact_same_full_name_and_branch_applies(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    _dirs, employees, sync, org = _seed(conn, session)
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
                    note="from-exact-package",
                )
            ]
        }
    )
    sync.apply_employees(package)
    updated = EmployeeRepository(conn).get(emp_id)
    assert updated is not None
    assert updated.note == "from-exact-package"
    assert updated.full_name == "Иванов Иван Иванович"
    assert updated.branch_id == org["branch_id"]
    assert _count_employees(conn) == 1
    conn.close()


def test_locally_anonymized_card_with_original_name_package_is_conflict(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    _dirs, employees, sync, org = _seed(conn, session)
    emp_id = _create_employee(employees, org, full_name="Иванов Иван Иванович")
    record = EmployeeRepository(conn).get(emp_id)
    assert record is not None
    # Simulate local anonymization in the test only (E10 not implemented).
    EmployeeRepository(conn).update(
        emp_id,
        full_name="обезличено",
        position_id=record.position_id,
        branch_id=record.branch_id,
        department_id=record.department_id,
        employment_type_id=record.employment_type_id,
        updated_at=_T0,
        division_id=record.division_id,
        note=record.note,
    )
    conn.commit()
    anonymized = EmployeeRepository(conn).get(emp_id)
    assert anonymized is not None
    assert anonymized.full_name == "обезличено"
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _employee_row(
                    conn,
                    org,
                    external_id=record.external_id,
                    full_name="Иванов Иван Иванович",
                    note="old-package-must-not-restore",
                )
            ]
        }
    )
    with pytest.raises(EmployeeSyncConflictError) as exc_info:
        sync.apply_employees(package)
    assert exc_info.value.details[0].status == EmployeeMatchStatus.CONFLICT
    after = EmployeeRepository(conn).get(emp_id)
    assert after is not None
    assert after.full_name == "обезличено"
    assert after.note == anonymized.note
    conn.close()
