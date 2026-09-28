"""ADR-0013 Checkpoint 1: confirmable LOW/AMBIGUOUS resolutions on apply."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from data.employees import EmployeeRepository
from domain.directory_sync import DirectorySyncPackage
from domain.employee import EmployeeCreateInput
from domain.employee_reconciliation import (
    EmployeeMatchResolution,
    EmployeeMatchResolutionChoice,
    EmployeeMatchStatus,
    EmployeeSyncApplyError,
    EmployeeSyncConflictError,
)
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
    branch_id = directories.create_branch("Филиал")
    dept_id = directories.create_department(branch_id, "Деп")
    div_id = directories.create_division(branch_id, dept_id, "Отдел")
    pos_id = directories.create_position(branch_id, "Инженер")
    org = {
        "branch_id": branch_id,
        "department_id": dept_id,
        "division_id": div_id,
        "position_id": pos_id,
    }
    return directories, employees, sync, org


def _row(conn, org: dict[str, int], *, external_id: str, full_name: str) -> dict[str, object]:
    from data.directories import (
        BranchRepository,
        DepartmentRepository,
        DivisionRepository,
        PositionRepository,
    )

    branch = BranchRepository(conn).get(org["branch_id"])
    dept = DepartmentRepository(conn).get(org["department_id"])
    div = DivisionRepository(conn).get(org["division_id"])
    pos = PositionRepository(conn).get(org["position_id"])
    assert branch and dept and div and pos
    return {
        "id": 9001,
        "external_id": external_id,
        "full_name": full_name,
        "position_external_id": pos.external_id,
        "branch_external_id": branch.external_id,
        "department_external_id": dept.external_id,
        "division_external_id": div.external_id,
        "employment_type_id": 1,
        "note": "from-package",
        "hire_date": None,
        "contacts": None,
        "home_address": None,
        "social_insurance_number": None,
        "needs_org_review": False,
        "is_archived": False,
        "created_at": _T0,
        "updated_at": _T0,
    }


def _create_local(employees: EmployeeService, org: dict[str, int], full_name: str) -> int:
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


def test_low_attach_existing_updates_card_without_rewriting_external_id(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    _dirs, employees, sync, org = _seed(conn, session)
    local_id = _create_local(employees, org, "Сидоров Сидор Сидорович")
    local_before = EmployeeRepository(conn).get(local_id)
    assert local_before is not None
    local_ext = local_before.external_id
    package_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _row(conn, org, external_id=package_ext, full_name="Сидоров Сидор Сидорович")
            ]
        }
    )
    plan = sync.build_employee_plan(package)
    assert not plan.conflicts
    assert len(plan.confirmable) == 1
    assert plan.confirmable[0].match.status is EmployeeMatchStatus.LOW

    sync.apply_employee_plan(
        plan,
        {
            package_ext: EmployeeMatchResolutionChoice(
                action=EmployeeMatchResolution.ATTACH_EXISTING
            )
        },
    )
    local_after = EmployeeRepository(conn).get(local_id)
    assert local_after is not None
    assert local_after.external_id == local_ext  # not rewritten
    assert local_after.note == "from-package"
    assert EmployeeRepository(conn).get_by_external_id(package_ext) is None
    assert int(conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]) == 1
    conn.close()


def test_low_create_new_inserts_row(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    _dirs, employees, sync, org = _seed(conn, session)
    _create_local(employees, org, "Сидоров Сидор Сидорович")
    package_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _row(conn, org, external_id=package_ext, full_name="Сидоров Сидор Сидорович")
            ]
        }
    )
    plan = sync.build_employee_plan(package)
    sync.apply_employee_plan(
        plan,
        {
            package_ext: EmployeeMatchResolutionChoice(
                action=EmployeeMatchResolution.CREATE_NEW
            )
        },
    )
    created = EmployeeRepository(conn).get_by_external_id(package_ext)
    assert created is not None
    assert created.full_name == "Сидоров Сидор Сидорович"
    assert int(conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]) == 2
    conn.close()


def test_ambiguous_attach_existing_valid_candidate(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    _dirs, employees, sync, org = _seed(conn, session)
    id_a = _create_local(employees, org, "Новиков Николай Николаевич")
    id_b = _create_local(employees, org, "Новиков Николай Николаевич")
    package_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _row(
                    conn,
                    org,
                    external_id=package_ext,
                    full_name="Новиков Николай Николаевич",
                )
            ]
        }
    )
    plan = sync.build_employee_plan(package)
    assert plan.confirmable[0].match.status is EmployeeMatchStatus.AMBIGUOUS
    candidates = plan.confirmable[0].match.candidate_employee_ids
    assert set(candidates) == {id_a, id_b}

    sync.apply_employee_plan(
        plan,
        {
            package_ext: EmployeeMatchResolutionChoice(
                action=EmployeeMatchResolution.ATTACH_EXISTING,
                attach_employee_id=id_b,
            )
        },
    )
    updated = EmployeeRepository(conn).get(id_b)
    assert updated is not None
    assert updated.note == "from-package"
    assert updated.external_id != package_ext
    assert int(conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]) == 2
    conn.close()


def test_ambiguous_attach_existing_invalid_candidate_raises(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    _dirs, employees, sync, org = _seed(conn, session)
    _create_local(employees, org, "Новиков Николай Николаевич")
    _create_local(employees, org, "Новиков Николай Николаевич")
    stranger = _create_local(employees, org, "Другой Человек")
    package_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _row(
                    conn,
                    org,
                    external_id=package_ext,
                    full_name="Новиков Николай Николаевич",
                )
            ]
        }
    )
    plan = sync.build_employee_plan(package)
    with pytest.raises(EmployeeSyncApplyError, match="not among"):
        sync.apply_employee_plan(
            plan,
            {
                package_ext: EmployeeMatchResolutionChoice(
                    action=EmployeeMatchResolution.ATTACH_EXISTING,
                    attach_employee_id=stranger,
                )
            },
        )
    assert int(conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]) == 3
    conn.close()


def test_ambiguous_create_new(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    _dirs, employees, sync, org = _seed(conn, session)
    _create_local(employees, org, "Новиков Николай Николаевич")
    _create_local(employees, org, "Новиков Николай Николаевич")
    package_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _row(
                    conn,
                    org,
                    external_id=package_ext,
                    full_name="Новиков Николай Николаевич",
                )
            ]
        }
    )
    plan = sync.build_employee_plan(package)
    sync.apply_employee_plan(
        plan,
        {
            package_ext: EmployeeMatchResolutionChoice(
                action=EmployeeMatchResolution.CREATE_NEW
            )
        },
    )
    assert EmployeeRepository(conn).get_by_external_id(package_ext) is not None
    assert int(conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]) == 3
    conn.close()


def test_missing_resolution_raises_conflict(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    _dirs, employees, sync, org = _seed(conn, session)
    _create_local(employees, org, "Сидоров Сидор Сидорович")
    package_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "employees": [
                _row(conn, org, external_id=package_ext, full_name="Сидоров Сидор Сидорович")
            ]
        }
    )
    plan = sync.build_employee_plan(package)
    with pytest.raises(EmployeeSyncConflictError) as exc_info:
        sync.apply_employee_plan(plan)
    assert exc_info.value.details[0].status is EmployeeMatchStatus.LOW
    assert exc_info.value.details[0].external_id == package_ext
    conn.close()
