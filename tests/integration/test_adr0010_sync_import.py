"""ADR-0010 Part 4a: apply directory sync packages (directories only)."""

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
from domain.directory_sync import DirectorySyncConflictError, DirectorySyncPackage
from domain.employee import EmployeeCreateInput
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.directory_sync_import import DirectorySyncImportService
from services.employees import EmployeeService
from services.installation_identity import InstallationIdentityService

_T0 = "2026-09-17T10:00:00Z"
_T1 = "2026-09-17T11:00:00Z"

_DIRECTORY_TABLES = ("branches", "departments", "divisions", "positions")


def _open(tmp_path: Path, *, clock: str = _T0):
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: clock).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


def _ensure_home_branch(
    conn,
    session,
    directories: DirectoryService,
    *,
    branch_id: int | None = None,
    new_name: str | None = None,
) -> None:
    identity = InstallationIdentityService(conn, session, directories=directories)
    if identity.get_home_branch() is not None:
        return
    if branch_id is not None:
        identity.set_home_branch(existing_branch_id=branch_id)
    elif new_name is not None:
        identity.set_home_branch(new_branch_name=new_name)
    else:
        raise ValueError("branch_id or new_name required")


def _services(conn, session, *, clock: str = _T0):
    directories = DirectoryService(conn, session, clock=lambda: clock)
    employees = EmployeeService(conn, session, clock=lambda: clock)
    importer = DirectorySyncImportService(conn, session, clock=lambda: clock)
    return directories, employees, importer


def _dump_directories(conn) -> dict[str, list[tuple]]:
    """Full dump of the four directory tables for byte-for-byte compare."""
    out: dict[str, list[tuple]] = {}
    for table in _DIRECTORY_TABLES:
        out[table] = list(conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall())
    return out


def _branch_row(
    *,
    package_id: int,
    external_id: str,
    name: str,
    is_archived: bool = False,
) -> dict[str, object]:
    return {
        "id": package_id,
        "external_id": external_id,
        "name": name,
        "is_archived": is_archived,
        "created_at": _T0,
        "updated_at": _T0,
    }


def _dept_row(
    *,
    package_id: int,
    external_id: str,
    branch_external_id: str,
    name: str,
    is_archived: bool = False,
) -> dict[str, object]:
    return {
        "id": package_id,
        "external_id": external_id,
        "branch_external_id": branch_external_id,
        "name": name,
        "is_archived": is_archived,
        "created_at": _T0,
        "updated_at": _T0,
    }


def _div_row(
    *,
    package_id: int,
    external_id: str,
    branch_external_id: str,
    department_external_id: str | None,
    name: str,
    is_archived: bool = False,
) -> dict[str, object]:
    return {
        "id": package_id,
        "external_id": external_id,
        "branch_external_id": branch_external_id,
        "department_external_id": department_external_id,
        "name": name,
        "is_archived": is_archived,
        "created_at": _T0,
        "updated_at": _T0,
    }


def _pos_row(
    *,
    package_id: int,
    external_id: str,
    branch_external_id: str,
    name: str,
    department_required: bool = False,
    division_required: bool = False,
    is_archived: bool = False,
) -> dict[str, object]:
    return {
        "id": package_id,
        "external_id": external_id,
        "branch_external_id": branch_external_id,
        "name": name,
        "department_required": department_required,
        "division_required": division_required,
        "is_archived": is_archived,
        "created_at": _T0,
        "updated_at": _T0,
    }


@pytest.mark.acceptance
def test_adr0010_apply_creates_new_branch_from_package(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, _employees, importer = _services(conn, session)
    _ensure_home_branch(conn, session, directories, new_name="Домашний филиал")
    ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "branches": [_branch_row(package_id=9001, external_id=ext, name="Филиал Удалённый")]
        }
    )
    importer.apply_package(package)
    local = BranchRepository(conn).get_by_external_id(ext)
    assert local is not None
    assert local.external_id == ext
    assert local.name == "Филиал Удалённый"
    assert local.id != 9001  # local PK is independent; identity is external_id
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_updates_existing_entity_by_external_id(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, _employees, importer = _services(conn, session)
    branch_id = directories.create_branch("Старое имя")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    local = BranchRepository(conn).get(branch_id)
    assert local is not None
    package = DirectorySyncPackage(
        tables={
            "branches": [
                _branch_row(
                    package_id=42,
                    external_id=local.external_id,
                    name="Новое имя",
                )
            ]
        }
    )
    importer.apply_package(package)
    updated = BranchRepository(conn).get(branch_id)
    assert updated is not None
    assert updated.id == branch_id
    assert updated.external_id == local.external_id
    assert updated.name == "Новое имя"
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_noop_when_package_matches_local_state(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, _employees, importer = _services(conn, session)
    branch_id = directories.create_branch("Филиал")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    local = BranchRepository(conn).get(branch_id)
    assert local is not None
    before = _dump_directories(conn)
    package = DirectorySyncPackage(
        tables={
            "branches": [
                _branch_row(
                    package_id=branch_id,
                    external_id=local.external_id,
                    name=local.name,
                    is_archived=local.is_archived,
                )
            ]
        }
    )
    importer.apply_package(package)
    assert _dump_directories(conn) == before
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_processes_parents_before_children(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories, _employees, importer = _services(conn, session)
    branch_id = directories.create_branch("Филиал")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    branch = BranchRepository(conn).get(branch_id)
    assert branch is not None
    dept_ext = str(uuid.uuid4())
    div_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "branches": [
                _branch_row(
                    package_id=10,
                    external_id=branch.external_id,
                    name=branch.name,
                )
            ],
            "departments": [
                _dept_row(
                    package_id=20,
                    external_id=dept_ext,
                    branch_external_id=branch.external_id,
                    name="Новый департамент",
                )
            ],
            "divisions": [
                _div_row(
                    package_id=30,
                    external_id=div_ext,
                    branch_external_id=branch.external_id,
                    department_external_id=dept_ext,
                    name="Новый отдел",
                )
            ],
        }
    )
    importer.apply_package(package)
    dept = DepartmentRepository(conn).get_by_external_id(dept_ext)
    div = DivisionRepository(conn).get_by_external_id(div_ext)
    assert dept is not None and div is not None
    assert dept.branch_id == branch_id
    assert div.department_id == dept.id
    assert div.branch_id == branch_id
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_rejects_whole_package_when_position_policy_change_breaks_employee(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, importer = _services(conn, session)
    branch_id = directories.create_branch("Филиал")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    pos_id = directories.create_position(branch_id, "Бухгалтер")
    employees.create_employee(
        EmployeeCreateInput(
            full_name="Иванов Иван",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=None,
            division_id=None,
            employment_type_id=1,
        )
    )
    branch = BranchRepository(conn).get(branch_id)
    pos = PositionRepository(conn).get(pos_id)
    assert branch is not None and pos is not None
    before = _dump_directories(conn)
    package = DirectorySyncPackage(
        tables={
            "branches": [
                _branch_row(
                    package_id=branch_id,
                    external_id=branch.external_id,
                    name=branch.name,
                )
            ],
            "positions": [
                _pos_row(
                    package_id=pos_id,
                    external_id=pos.external_id,
                    branch_external_id=branch.external_id,
                    name=pos.name,
                    department_required=True,
                )
            ],
        }
    )
    with pytest.raises(DirectorySyncConflictError) as exc_info:
        importer.apply_package(package)
    assert exc_info.value.affected_employees
    assert any(name == "Иванов Иван" for _, name in exc_info.value.affected_employees)
    assert _dump_directories(conn) == before
    still = PositionRepository(conn).get(pos_id)
    assert still is not None
    assert still.department_required is False
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_rejects_when_division_reparenting_breaks_employee(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, importer = _services(conn, session)
    branch_id = directories.create_branch("Филиал")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    dept_a = directories.create_department(branch_id, "Департамент A")
    dept_b = directories.create_department(branch_id, "Департамент B")
    div_id = directories.create_division(branch_id, dept_a, "Отдел")
    pos_id = directories.create_position(branch_id, "Инженер")
    employees.create_employee(
        EmployeeCreateInput(
            full_name="Петров Пётр",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=dept_a,
            division_id=div_id,
            employment_type_id=1,
        )
    )
    branch = BranchRepository(conn).get(branch_id)
    da = DepartmentRepository(conn).get(dept_a)
    db = DepartmentRepository(conn).get(dept_b)
    div = DivisionRepository(conn).get(div_id)
    assert branch and da and db and div
    before = _dump_directories(conn)
    package = DirectorySyncPackage(
        tables={
            "branches": [
                _branch_row(
                    package_id=1,
                    external_id=branch.external_id,
                    name=branch.name,
                )
            ],
            "departments": [
                _dept_row(
                    package_id=10,
                    external_id=da.external_id,
                    branch_external_id=branch.external_id,
                    name=da.name,
                ),
                _dept_row(
                    package_id=11,
                    external_id=db.external_id,
                    branch_external_id=branch.external_id,
                    name=db.name,
                ),
            ],
            "divisions": [
                _div_row(
                    package_id=20,
                    external_id=div.external_id,
                    branch_external_id=branch.external_id,
                    department_external_id=db.external_id,  # reparent to B
                    name=div.name,
                )
            ],
        }
    )
    with pytest.raises(DirectorySyncConflictError):
        importer.apply_package(package)
    assert _dump_directories(conn) == before
    still = DivisionRepository(conn).get(div_id)
    assert still is not None
    assert still.department_id == dept_a
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_ignores_archived_employees_when_checking_for_breakage(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, importer = _services(conn, session)
    branch_id = directories.create_branch("Филиал")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    pos_id = directories.create_position(branch_id, "Бухгалтер")
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Архивный",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=None,
            division_id=None,
            employment_type_id=1,
        )
    )
    employees.archive_employee(emp_id)
    branch = BranchRepository(conn).get(branch_id)
    pos = PositionRepository(conn).get(pos_id)
    assert branch and pos
    package = DirectorySyncPackage(
        tables={
            "branches": [
                _branch_row(
                    package_id=branch_id,
                    external_id=branch.external_id,
                    name=branch.name,
                )
            ],
            "positions": [
                _pos_row(
                    package_id=pos_id,
                    external_id=pos.external_id,
                    branch_external_id=branch.external_id,
                    name=pos.name,
                    department_required=True,
                )
            ],
        }
    )
    importer.apply_package(package)
    updated = PositionRepository(conn).get(pos_id)
    assert updated is not None
    assert updated.department_required is True
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_is_all_or_nothing_across_multiple_tables(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, employees, importer = _services(conn, session)
    branch_id = directories.create_branch("Старое имя филиала")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    pos_id = directories.create_position(branch_id, "Бухгалтер")
    employees.create_employee(
        EmployeeCreateInput(
            full_name="Сидоров",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=None,
            division_id=None,
            employment_type_id=1,
        )
    )
    branch = BranchRepository(conn).get(branch_id)
    pos = PositionRepository(conn).get(pos_id)
    assert branch and pos
    before = _dump_directories(conn)
    package = DirectorySyncPackage(
        tables={
            "branches": [
                _branch_row(
                    package_id=branch_id,
                    external_id=branch.external_id,
                    name="Безопасное переименование",
                )
            ],
            "positions": [
                _pos_row(
                    package_id=pos_id,
                    external_id=pos.external_id,
                    branch_external_id=branch.external_id,
                    name=pos.name,
                    department_required=True,
                )
            ],
        }
    )
    with pytest.raises(DirectorySyncConflictError):
        importer.apply_package(package)
    assert _dump_directories(conn) == before
    still_branch = BranchRepository(conn).get(branch_id)
    still_pos = PositionRepository(conn).get(pos_id)
    assert still_branch is not None and still_branch.name == "Старое имя филиала"
    assert still_pos is not None and still_pos.department_required is False
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_resolves_parent_by_external_id_when_parent_table_omitted_from_package(
    tmp_path: Path,
) -> None:
    """Sender local ids must never be used when the parent table is omitted.

    Receiver already has: local id 1 = unrelated own branch, local id 2 =
    previously-synced sender branch (matched by external_id). Package contains
    only a new department whose branch_external_id points at the second branch.
    """
    conn, session = _open(tmp_path)
    directories, _employees, importer = _services(conn, session)
    own_id = directories.create_branch("Receiver's own unrelated branch")
    _ensure_home_branch(conn, session, directories, branch_id=own_id)
    synced_id = directories.create_branch("Previously synced sender branch")
    own = BranchRepository(conn).get(own_id)
    synced = BranchRepository(conn).get(synced_id)
    assert own is not None and synced is not None
    assert own.id == 1
    assert synced.id == 2
    assert own.external_id != synced.external_id

    dept_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "departments": [
                _dept_row(
                    package_id=1,  # sender-local; must be ignored for FK resolution
                    external_id=dept_ext,
                    branch_external_id=synced.external_id,
                    name="New department from sender",
                )
            ]
        }
    )
    assert "branches" not in package.tables
    importer.apply_package(package)

    dept = DepartmentRepository(conn).get_by_external_id(dept_ext)
    assert dept is not None
    assert dept.branch_id == synced.id
    assert dept.branch_id != own.id
    conn.close()


@pytest.mark.acceptance
def test_adr0010_apply_rejects_package_when_referenced_parent_is_missing_locally(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories, _employees, importer = _services(conn, session)
    _ensure_home_branch(conn, session, directories, new_name="Домашний филиал")
    before = _dump_directories(conn)
    missing_branch_ext = str(uuid.uuid4())
    package = DirectorySyncPackage(
        tables={
            "departments": [
                _dept_row(
                    package_id=1,
                    external_id=str(uuid.uuid4()),
                    branch_external_id=missing_branch_ext,
                    name="Orphan department",
                )
            ]
        }
    )
    with pytest.raises(ValueError, match="cannot resolve branch external_id"):
        importer.apply_package(package)
    assert _dump_directories(conn) == before
    conn.close()
