"""ADR-0010 Part 1: positions become branch-scoped."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
import sqlcipher3

from data.db import Connection, connect, create_database, generate_master_key
from data.employees import EmployeeRepository
from data.migrations import apply_pending_migrations, current_version, default_migrations_dir
from domain.employee import EmployeeCreateInput
from services.bootstrap import BootstrapService
from services.directories import DirectoryError, DirectoryService
from services.employees import EmployeeError, EmployeeService

_NOW = "2026-08-01T10:00:00Z"


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target


def _seed_post_0012_with_position(conn: Connection) -> None:
    conn.execute(
        "INSERT INTO branches (id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 'Филиал Север', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO positions ("
        " id, name, department_required, division_required, is_archived, created_at, updated_at"
        ") VALUES (1, 'Инженер', 0, 0, 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.commit()


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


@pytest.mark.acceptance
def test_adr0010_migration_aborts_when_positions_nonempty(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v12 = _migrations_through(12, tmp_path / "v12")
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v12) == list(range(1, 13))
    _seed_post_0012_with_position(conn)
    conn.close()

    conn2 = connect(path, key)
    with pytest.raises(sqlcipher3.DatabaseError):
        apply_pending_migrations(conn2)
    assert current_version(conn2) == 12
    conn2.close()


@pytest.mark.acceptance
def test_adr0010_migration_succeeds_on_empty_positions_table(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v12 = _migrations_through(12, tmp_path / "v12")
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v12) == list(range(1, 13))
    assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
    conn.close()

    conn2 = connect(path, key)
    applied = apply_pending_migrations(conn2)
    assert applied == [13, 14]
    assert current_version(conn2) == 14
    cols = {row[1] for row in conn2.execute("PRAGMA table_info(positions)").fetchall()}
    assert "branch_id" in cols
    conn2.close()


@pytest.mark.acceptance
def test_adr0010_employee_position_must_belong_to_employee_branch(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, _employees = _services(conn, session)
    branch_a = directories.create_branch("Филиал A")
    branch_b = directories.create_branch("Филиал B")
    pos_id = directories.create_position(branch_a, "Инженер")
    et_id = directories.list_employment_types(active_only=True)[0].id
    repo = EmployeeRepository(conn)

    emp_id = repo.create(
        external_id=str(uuid.uuid4()),
        full_name="Сотрудник A",
        position_id=pos_id,
        branch_id=branch_a,
        department_id=None,
        employment_type_id=et_id,
        created_at=_NOW,
    )
    conn.commit()
    assert emp_id > 0

    with pytest.raises(
        sqlcipher3.DatabaseError,
        match="employee position does not belong to branch",
    ):
        repo.create(
            external_id=str(uuid.uuid4()),
            full_name="Сотрудник B",
            position_id=pos_id,
            branch_id=branch_b,
            department_id=None,
            employment_type_id=et_id,
            created_at=_NOW,
        )
        conn.commit()
    conn.close()


@pytest.mark.acceptance
def test_adr0010_create_position_requires_branch(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories, _employees = _services(conn, session)
    branch_id = directories.create_branch("Филиал Центр")
    pos_id = directories.create_position(branch_id, "Бухгалтер")
    pos = directories.get_position(pos_id)
    assert pos is not None
    assert pos.branch_id == branch_id
    with pytest.raises(DirectoryError, match="branch not found"):
        directories.create_position(9999, "Призрак")
    conn.close()


@pytest.mark.acceptance
def test_adr0010_list_positions_filtered_by_branch(tmp_path: Path) -> None:
    conn, session = _open_db(tmp_path)
    directories, _employees = _services(conn, session)
    branch_a = directories.create_branch("Филиал A")
    branch_b = directories.create_branch("Филиал B")
    pos_a = directories.create_position(branch_a, "Инженер A")
    pos_b = directories.create_position(branch_b, "Инженер B")

    only_a = directories.list_positions(branch_id=branch_a)
    only_b = directories.list_positions(branch_id=branch_b)
    assert [p.id for p in only_a] == [pos_a]
    assert [p.id for p in only_b] == [pos_b]
    conn.close()


@pytest.mark.acceptance
def test_adr0010_service_layer_rejects_cross_branch_position_assignment(
    tmp_path: Path,
) -> None:
    conn, session = _open_db(tmp_path)
    directories, employees = _services(conn, session)
    branch_a = directories.create_branch("Филиал A")
    branch_b = directories.create_branch("Филиал B")
    pos_id = directories.create_position(branch_a, "Директор")
    et_id = directories.list_employment_types(active_only=True)[0].id

    with pytest.raises(EmployeeError, match="position does not belong to employee's branch"):
        employees.create_employee(
            EmployeeCreateInput(
                full_name="Чужой директор",
                position_id=pos_id,
                branch_id=branch_b,
                department_id=None,
                division_id=None,
                employment_type_id=et_id,
            )
        )
    conn.close()
