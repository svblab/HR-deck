"""ADR-0010 Part 3: table-level incremental directory sync export."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from data.transport_crypto import generate_bootstrap_keypair, generate_signing_keypair
from domain.employee import EmployeeCreateInput
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.directory_sync import DirectorySyncService
from services.employees import EmployeeService
from services.installation_identity import InstallationIdentityService
from services.transport_keys import TransportKeyStore

_T0 = "2026-09-17T10:00:00Z"
_T1 = "2026-09-17T11:00:00Z"
_T2 = "2026-09-17T12:00:00Z"
_T3 = "2026-09-17T13:00:00Z"


def _open(tmp_path: Path, *, clock: str = _T0):
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: clock).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


def _direction_id(conn, *, clock: str = _T0) -> int:
    store = TransportKeyStore(conn, clock=lambda: clock)
    local = store.ensure_local_installation(display_label="Local")
    signing = generate_signing_keypair()
    bootstrap = generate_bootstrap_keypair()
    peer_installation_id = str(uuid.uuid4())
    peer_id = store.register_peer_trust(
        peer_installation_id=peer_installation_id,
        display_label="Peer",
        signing_public_key=signing.public_key,
        signing_fingerprint=signing.fingerprint,
        bootstrap_public_key=bootstrap.public_key,
        bootstrap_fingerprint=bootstrap.fingerprint,
    )
    direction = store.ensure_direction(
        sender_installation_id=local.installation_id,
        recipient_installation_id=peer_installation_id,
        peer_trust_id=peer_id,
    )
    conn.commit()
    return direction.id


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


def _services(conn, session, *, clock: str):
    directories = DirectoryService(conn, session, clock=lambda: clock)
    employees = EmployeeService(conn, session, clock=lambda: clock)
    sync = DirectorySyncService(conn, session)
    return directories, employees, sync


@pytest.mark.acceptance
def test_adr0010_export_includes_table_when_any_row_changed_since_watermark(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path, clock=_T0)
    direction_id = _direction_id(conn)
    directories, _employees, sync = _services(conn, session, clock=_T0)
    branch_id = directories.create_branch("Филиал A")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    pkg = sync.build_export_package(direction_id)
    assert "branches" in pkg.tables
    sync.record_export(direction_id, ["branches"], exported_at=_T1)

    directories_later = DirectoryService(conn, session, clock=lambda: _T2)
    directories_later.create_branch("Филиал B")
    directories_later.create_department(branch_id, "Новый департамент")
    pkg2 = sync.build_export_package(direction_id)
    assert "departments" in pkg2.tables
    conn.close()


@pytest.mark.acceptance
def test_adr0010_export_omits_table_when_nothing_changed_since_watermark(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path, clock=_T0)
    direction_id = _direction_id(conn)
    directories, _employees, sync = _services(conn, session, clock=_T0)
    branch_id = directories.create_branch("Филиал A")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    sync.record_export(direction_id, ["branches"], exported_at=_T1)

    pkg = sync.build_export_package(direction_id)
    assert "branches" not in pkg.tables
    conn.close()


@pytest.mark.acceptance
def test_adr0010_export_includes_all_rows_of_a_changed_table_not_just_changed_ones(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path, clock=_T0)
    direction_id = _direction_id(conn)
    directories, _employees, sync = _services(conn, session, clock=_T0)
    branch_a = directories.create_branch("Филиал Старый")
    _ensure_home_branch(conn, session, directories, branch_id=branch_a)
    sync.record_export(direction_id, ["branches"], exported_at=_T1)

    directories_later = DirectoryService(conn, session, clock=lambda: _T2)
    directories_later.create_branch("Филиал Новый")
    directories_later.rename_branch(branch_a, "Филиал Старый переименован")
    pkg = sync.build_export_package(direction_id)
    names = {row["name"] for row in pkg.tables["branches"]}
    assert names == {"Филиал Старый переименован"}
    assert len(pkg.tables["branches"]) == 1
    assert any(row["id"] == branch_a for row in pkg.tables["branches"])
    conn.close()


@pytest.mark.acceptance
def test_adr0010_export_includes_archived_rows(tmp_path: Path) -> None:
    conn, session = _open(tmp_path, clock=_T0)
    direction_id = _direction_id(conn)
    directories, _employees, sync = _services(conn, session, clock=_T0)
    branch_id = directories.create_branch("Филиал Архив")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    directories.archive_branch(branch_id)

    pkg = sync.build_export_package(direction_id)
    archived = [row for row in pkg.tables["branches"] if row["id"] == branch_id]
    assert len(archived) == 1
    assert archived[0]["is_archived"] is True
    conn.close()


@pytest.mark.acceptance
def test_adr0010_export_with_no_watermark_row_includes_everything(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path, clock=_T0)
    direction_id = _direction_id(conn)
    directories, employees, sync = _services(conn, session, clock=_T0)
    branch_id = directories.create_branch("Филиал")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    dept_id = directories.create_department(branch_id, "Департамент")
    directories.create_division(branch_id, dept_id, "Отдел")
    pos_id = directories.create_position(branch_id, "Инженер")
    employees.create_employee(
        EmployeeCreateInput(
            full_name="Иванов Иван",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=dept_id,
            division_id=None,
            employment_type_id=1,
        )
    )

    pkg = sync.build_export_package(direction_id)
    assert set(pkg.tables) == {
        "branches",
        "departments",
        "divisions",
        "positions",
        "employees",
    }
    assert not pkg.is_empty()
    conn.close()


@pytest.mark.acceptance
def test_adr0010_record_export_only_bumps_watermark_for_tables_actually_exported(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path, clock=_T0)
    direction_id = _direction_id(conn)
    directories, _employees, sync = _services(conn, session, clock=_T0)
    branch_id = directories.create_branch("Филиал")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    directories.create_department(branch_id, "Департамент")

    sync.record_export(direction_id, ["branches", "departments"], exported_at=_T1)
    sync.record_export(direction_id, ["branches"], exported_at=_T3)

    rows = {
        str(r[0]): str(r[1])
        for r in conn.execute(
            "SELECT table_name, last_exported_at FROM sync_watermarks WHERE direction_id = ?",
            (direction_id,),
        ).fetchall()
    }
    assert rows["branches"] == _T3
    assert rows["departments"] == _T1
    conn.close()


@pytest.mark.acceptance
def test_adr0010_package_rows_are_json_serializable(tmp_path: Path) -> None:
    conn, session = _open(tmp_path, clock=_T0)
    direction_id = _direction_id(conn)
    directories, employees, sync = _services(conn, session, clock=_T0)
    branch_id = directories.create_branch("Филиал")
    _ensure_home_branch(conn, session, directories, branch_id=branch_id)
    dept_id = directories.create_department(branch_id, "Департамент")
    directories.create_division(branch_id, dept_id, "Отдел")
    pos_id = directories.create_position(branch_id, "Инженер")
    employees.create_employee(
        EmployeeCreateInput(
            full_name="Петров Пётр",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=None,
            division_id=None,
            employment_type_id=1,
        )
    )
    pkg = sync.build_export_package(direction_id)
    payload = json.dumps(pkg.tables, ensure_ascii=False)
    assert isinstance(payload, str)
    assert "Филиал" in payload

    # Child rows carry parent external_id strings, never sender-local integer FKs.
    branch_ext = pkg.tables["branches"][0]["external_id"]
    dept_row = pkg.tables["departments"][0]
    assert dept_row["branch_external_id"] == branch_ext
    assert "branch_id" not in dept_row
    div_row = pkg.tables["divisions"][0]
    assert div_row["branch_external_id"] == branch_ext
    assert div_row["department_external_id"] == dept_row["external_id"]
    assert "branch_id" not in div_row
    assert "department_id" not in div_row
    pos_row = pkg.tables["positions"][0]
    assert pos_row["branch_external_id"] == branch_ext
    assert "branch_id" not in pos_row
    emp_row = pkg.tables["employees"][0]
    assert emp_row["branch_external_id"] == branch_ext
    assert emp_row["position_external_id"] == pos_row["external_id"]
    assert emp_row["department_external_id"] is None
    assert emp_row["division_external_id"] is None
    assert emp_row["employment_type_id"] == 1
    assert "branch_id" not in emp_row
    assert "department_id" not in emp_row
    assert "division_id" not in emp_row
    assert "position_id" not in emp_row
    conn.close()
