"""ADR-0009 Phase 0: position org requirements schema and service rules."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from data.db import Connection, connect, create_database, generate_master_key
from data.directories import PositionRepository
from data.employees import EmployeeRepository
from data.migrations import apply_pending_migrations, current_version, default_migrations_dir
from domain.employee import EmployeeCreateInput, EmployeeUpdateInput
from services.bootstrap import BootstrapService
from services.directories import DirectoryError, DirectoryService
from services.employee_import import EmployeeImportService
from services.employees import EmployeeError, EmployeeService

_NOW = "2026-08-01T10:00:00Z"


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target


def _seed_post_0011(conn: Connection) -> dict[str, int]:
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
        "INSERT INTO divisions ("
        " id, branch_id, department_id, name, is_archived, created_at, updated_at"
        ") VALUES (1, 1, 1, 'Отдел платформы', 0, ?, ?)",
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
    return {"position_id": 1, "employee_id": 1}


def _open_db(tmp_path: Path) -> tuple[Connection, object]:
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: _NOW).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


def _services(conn: Connection, session: object) -> tuple[DirectoryService, EmployeeService]:
    directories = DirectoryService(conn, session, clock=lambda: _NOW)
    employees = EmployeeService(conn, session, clock=lambda: _NOW)
    return directories, employees


def _employee_input(
    *,
    directories: DirectoryService,
    branch_id: int,
    position_id: int,
    department_id: int | None = None,
    division_id: int | None = None,
    full_name: str = "Тестов Тест",
) -> EmployeeCreateInput:
    et_id = directories.list_employment_types(active_only=True)[0].id
    return EmployeeCreateInput(
        full_name=full_name,
        position_id=position_id,
        branch_id=branch_id,
        department_id=department_id,
        division_id=division_id,
        employment_type_id=et_id,
    )


@pytest.mark.acceptance
def test_adr0009_migration_position_org_requirements_on_nonempty_db(
    tmp_path: Path,
) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v11 = _migrations_through(11, tmp_path / "v11")
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v11) == list(range(1, 12))
    ids = _seed_post_0011(conn)
    pos_count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    emp_count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    conn.close()

    conn2 = connect(path, key)
    mig_through_12 = _migrations_through(12, tmp_path / "through12")
    applied = apply_pending_migrations(conn2, migrations_dir=mig_through_12)
    assert applied == [12]
    assert current_version(conn2) == 12
    assert conn2.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == pos_count
    assert conn2.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == emp_count
    pos_row = conn2.execute(
        "SELECT department_required, division_required FROM positions WHERE id = ?",
        (ids["position_id"],),
    ).fetchone()
    assert pos_row == (0, 0)
    emp_row = conn2.execute(
        "SELECT needs_org_review FROM employees WHERE id = ?",
        (ids["employee_id"],),
    ).fetchone()
    assert emp_row == (0,)
    conn2.close()


@pytest.mark.acceptance
def test_adr0009_position_requirements_default_to_false(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories, _employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал T")
    pos_id = directories.create_position(branch_id, "Аналитик")
    pos = directories._positions.get(pos_id)
    assert pos is not None
    assert pos.department_required is False
    assert pos.division_required is False
    conn.close()


@pytest.mark.acceptance
def test_adr0009_employee_service_requires_department_when_position_demands_it(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал A")
    pos_id = directories.create_position(branch_id, "Директор")
    PositionRepository(conn).set_org_requirements(
        pos_id,
        department_required=True,
        division_required=False,
        updated_at=_NOW,
    )
    conn.commit()
    with pytest.raises(EmployeeError, match="department is required"):
        employees.create_employee(
            _employee_input(
                directories=directories,
                branch_id=branch_id,
                position_id=pos_id,
                department_id=None,
            )
        )
    conn.close()


@pytest.mark.acceptance
def test_adr0009_employee_service_requires_division_when_position_demands_it(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал B")
    dept_id = directories.create_department(branch_id, "Департамент B")
    pos_id = directories.create_position(branch_id, "Менеджер")
    div_id = directories.create_division(branch_id, dept_id, "Отдел B")
    PositionRepository(conn).set_org_requirements(
        pos_id,
        department_required=False,
        division_required=True,
        updated_at=_NOW,
    )
    conn.commit()
    with pytest.raises(EmployeeError, match="division is required"):
        employees.create_employee(
            _employee_input(
                directories=directories,
                branch_id=branch_id,
                position_id=pos_id,
                department_id=dept_id,
                division_id=None,
            )
        )
    employees.create_employee(
        _employee_input(
            directories=directories,
            branch_id=branch_id,
            position_id=pos_id,
            department_id=dept_id,
            division_id=div_id,
            full_name="Сотрудник с отделом",
        )
    )
    conn.close()


@pytest.mark.acceptance
def test_adr0009_division_required_without_department_forces_branch_direct_division(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал C")
    dept_id = directories.create_department(branch_id, "Департамент C")
    dept_div_id = directories.create_division(branch_id, dept_id, "Отдел C")
    branch_div_id = directories.create_division(branch_id, None, "Секретариат")
    pos_id = directories.create_position(branch_id, "Секретарь")
    PositionRepository(conn).set_org_requirements(
        pos_id,
        department_required=False,
        division_required=True,
        updated_at=_NOW,
    )
    conn.commit()
    with pytest.raises(EmployeeError, match="division department does not match"):
        employees.create_employee(
            _employee_input(
                directories=directories,
                branch_id=branch_id,
                position_id=pos_id,
                department_id=None,
                division_id=dept_div_id,
            )
        )
    employees.create_employee(
        _employee_input(
            directories=directories,
            branch_id=branch_id,
            position_id=pos_id,
            department_id=None,
            division_id=branch_div_id,
            full_name="Секретарь филиала",
        )
    )
    conn.close()


@pytest.mark.acceptance
def test_adr0009_preview_returns_empty_when_loosening_requirements(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, _employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал D")
    pos_id = directories.create_position(branch_id, "Руководитель")
    EmployeeRepository(conn).create(
        full_name="Без департамента",
        position_id=pos_id,
        branch_id=branch_id,
        department_id=None,
        employment_type_id=1,
        created_at=_NOW,
    )
    PositionRepository(conn).set_org_requirements(
        pos_id,
        department_required=True,
        division_required=False,
        updated_at=_NOW,
    )
    conn.commit()
    violators = directories.preview_position_requirement_change(
        pos_id, department_required=False, division_required=False
    )
    assert violators == []
    conn.close()


@pytest.mark.acceptance
def test_adr0009_preview_lists_violating_active_employees_only(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал E")
    pos_id = directories.create_position(branch_id, "Исполнитель")
    active_id = employees.create_employee(
        _employee_input(
            directories=directories,
            branch_id=branch_id,
            position_id=pos_id,
            full_name="Активный без департамента",
        )
    )
    archived_id = employees.create_employee(
        _employee_input(
            directories=directories,
            branch_id=branch_id,
            position_id=pos_id,
            full_name="Архивный без департамента",
        )
    )
    employees.archive_employee(archived_id)
    violators = directories.preview_position_requirement_change(
        pos_id, department_required=True, division_required=False
    )
    assert [v.id for v in violators] == [active_id]
    conn.close()


@pytest.mark.acceptance
def test_adr0009_apply_without_confirmation_raises_when_violators_exist(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал F")
    pos_id = directories.create_position(branch_id, "Специалист")
    employees.create_employee(
        _employee_input(
            directories=directories,
            branch_id=branch_id,
            position_id=pos_id,
            full_name="Нарушитель",
        )
    )
    with pytest.raises(DirectoryError, match="would violate"):
        directories.apply_position_requirement_change(
            pos_id,
            department_required=True,
            division_required=False,
            reset_violations=False,
        )
    pos = directories._positions.get(pos_id)
    assert pos is not None
    assert pos.department_required is False
    conn.close()


@pytest.mark.acceptance
def test_adr0009_apply_with_confirmation_resets_only_violating_fields(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал G")
    dept_id = directories.create_department(branch_id, "Департамент G")
    pos_id = directories.create_position(branch_id, "Координатор")
    emp_id = employees.create_employee(
        _employee_input(
            directories=directories,
            branch_id=branch_id,
            position_id=pos_id,
            department_id=dept_id,
            division_id=None,
            full_name="С департаментом без отдела",
        )
    )
    directories.apply_position_requirement_change(
        pos_id,
        department_required=False,
        division_required=True,
        reset_violations=True,
    )
    row = conn.execute(
        "SELECT department_id, division_id, needs_org_review FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert row == (dept_id, None, 1)
    conn.close()


@pytest.mark.acceptance
def test_adr0009_apply_sets_needs_org_review_and_writes_audit_log(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал H")
    pos_id = directories.create_position(branch_id, "Оператор")
    emp_id = employees.create_employee(
        _employee_input(
            directories=directories,
            branch_id=branch_id,
            position_id=pos_id,
            full_name="Под review",
        )
    )
    before = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    directories.apply_position_requirement_change(
        pos_id,
        department_required=True,
        division_required=False,
        reset_violations=True,
    )
    after = conn.execute("SELECT COUNT(*) FROM user_action_log").fetchone()[0]
    assert after == before + 1
    row = conn.execute(
        "SELECT needs_org_review FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()
    assert row == (1,)
    audit = conn.execute(
        "SELECT action_type, entity_id FROM user_action_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert audit == ("employee.org_review_reset", emp_id)
    conn.close()


@pytest.mark.acceptance
def test_adr0009_needs_org_review_cleared_on_next_compliant_save(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал I")
    dept_id = directories.create_department(branch_id, "Департамент I")
    pos_id = directories.create_position(branch_id, "Инженер I")
    emp_id = employees.create_employee(
        _employee_input(
            directories=directories,
            branch_id=branch_id,
            position_id=pos_id,
            full_name="Исправляемый",
        )
    )
    directories.apply_position_requirement_change(
        pos_id,
        department_required=True,
        division_required=False,
        reset_violations=True,
    )
    assert conn.execute(
        "SELECT needs_org_review FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()[0] == 1
    employees.update_employee(
        emp_id,
        EmployeeUpdateInput(
            full_name="Исправляемый",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=dept_id,
            employment_type_id=directories.list_employment_types(active_only=True)[0].id,
        ),
    )
    assert conn.execute(
        "SELECT needs_org_review FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()[0] == 0
    conn.close()


@pytest.mark.acceptance
def test_adr0009_employee_import_also_enforces_position_requirements(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    importer = EmployeeImportService(employees, directories, session)
    branch_id = directories.create_branch("Филиал J")
    pos_id = directories.create_position(branch_id, "Импортёр")
    et_name = directories.list_employment_types(active_only=True)[0].name
    PositionRepository(conn).set_org_requirements(
        pos_id,
        department_required=True,
        division_required=False,
        updated_at=_NOW,
    )
    conn.commit()
    pos = directories._positions.get(pos_id)
    branch = directories._branches.get(branch_id)
    assert pos is not None and branch is not None
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
                "Импорт Иван",
                pos.name,
                branch.name,
                "",
                "",
                et_name,
            ]
        ],
    )
    assert len(preview.ready) == 1
    with pytest.raises(EmployeeError, match="department is required"):
        importer.confirm(preview)
    conn.close()
