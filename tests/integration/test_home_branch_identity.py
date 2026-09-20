"""ADR-0007 addendum: home branch identity and export ownership scoping."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from data.transport_crypto import generate_bootstrap_keypair, generate_signing_keypair
from domain.directory_sync import DirectorySyncPackage
from domain.employee import EmployeeCreateInput, EmployeeUpdateInput
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.authentication import AuthenticationService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.directory_sync import DirectorySyncService
from services.directory_sync_import import DirectorySyncImportService
from services.employees import EmployeeService
from services.installation_identity import (
    HomeBranchNotSetError,
    InstallationIdentityAlreadySetError,
    InstallationIdentityService,
)
from services.session import SessionState
from services.transport_keys import TransportKeyStore

_T0 = "2026-09-20T10:00:00Z"
_T1 = "2026-09-20T11:00:00Z"
_T2 = "2026-09-20T12:00:00Z"


def _open(tmp_path: Path, *, clock: str = _T0) -> tuple[object, SessionState]:
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: clock).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session


def _direction_id(conn: object, *, clock: str = _T0) -> int:
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


def _identity(conn: object, session: SessionState, directories: DirectoryService):
    return InstallationIdentityService(conn, session, directories=directories)


def _set_home(
    conn: object,
    session: SessionState,
    directories: DirectoryService,
    *,
    branch_id: int | None = None,
    new_name: str | None = None,
) -> None:
    identity = _identity(conn, session, directories)
    if identity.get_home_branch() is not None:
        return
    if branch_id is not None:
        identity.set_home_branch(existing_branch_id=branch_id)
    elif new_name is not None:
        identity.set_home_branch(new_branch_name=new_name)
    else:
        raise ValueError("branch_id or new_name required")


def test_home_branch_unset_freezes_export_and_import(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    direction_id = _direction_id(conn)
    sync = DirectorySyncService(conn, session)
    importer = DirectorySyncImportService(conn, session, clock=lambda: _T0)

    with pytest.raises(HomeBranchNotSetError):
        sync.build_export_package(direction_id)
    with pytest.raises(HomeBranchNotSetError):
        importer.apply_package(DirectorySyncPackage(tables={}))

    conn.close()


def test_set_home_branch_creates_new_branch_atomically(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    identity = _identity(conn, session, directories)

    branch = identity.set_home_branch(new_branch_name="Филиал Домашний")

    assert branch.name == "Филиал Домашний"
    assert identity.get_home_branch() is not None
    assert identity.get_home_branch().external_id == branch.external_id
    assert len(directories.list_branches(active_only=False)) == 1
    conn.close()


def test_set_home_branch_rejects_second_call(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    identity = _identity(conn, session, directories)
    identity.set_home_branch(new_branch_name="Филиал A")

    with pytest.raises(InstallationIdentityAlreadySetError):
        identity.set_home_branch(new_branch_name="Филиал B")

    conn.close()


def test_only_administrator_can_set_home_branch(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    conn, admin, _code = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    mgr = AccountManagementService(conn, admin, db_path=db, clock=lambda: _T0)
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    hr = SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin.master_key,
    )
    directories = DirectoryService(conn, hr, clock=lambda: _T0)
    identity = _identity(conn, hr, directories)

    with pytest.raises(AuthorizationError):
        identity.set_home_branch(new_branch_name="Филиал HR")

    conn.close()


def test_export_includes_only_home_branch_row(tmp_path: Path) -> None:
    conn, session = _open(tmp_path)
    direction_id = _direction_id(conn)
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    home = _identity(conn, session, directories).set_home_branch(new_branch_name="Свой")
    directories.create_branch("Чужой")
    sync = DirectorySyncService(conn, session)

    pkg = sync.build_export_package(direction_id)
    assert "branches" in pkg.tables
    assert len(pkg.tables["branches"]) == 1
    assert pkg.tables["branches"][0]["external_id"] == home.external_id

    conn.close()


def test_export_scopes_by_current_branch_id(tmp_path: Path) -> None:
    conn, session = _open(tmp_path, clock=_T0)
    direction_id = _direction_id(conn)
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    home_id = _identity(conn, session, directories).set_home_branch(
        new_branch_name="Домашний"
    ).id
    foreign_id = directories.create_branch("Чужой")
    dept_home = directories.create_department(home_id, "Департамент дома")
    dept_foreign = directories.create_department(foreign_id, "Департамент чужой")
    pos_home = directories.create_position(home_id, "Инженер дома")
    pos_foreign = directories.create_position(foreign_id, "Инженер чужой")
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    employees.create_employee(
        EmployeeCreateInput(
            full_name="Свой сотрудник",
            position_id=pos_home,
            branch_id=home_id,
            department_id=dept_home,
            division_id=None,
            employment_type_id=1,
        )
    )
    employees.create_employee(
        EmployeeCreateInput(
            full_name="Чужой сотрудник",
            position_id=pos_foreign,
            branch_id=foreign_id,
            department_id=dept_foreign,
            division_id=None,
            employment_type_id=1,
        )
    )

    sync = DirectorySyncService(conn, session)
    pkg = sync.build_export_package(direction_id)

    assert {row["name"] for row in pkg.tables["departments"]} == {"Департамент дома"}
    assert {row["name"] for row in pkg.tables["positions"]} == {"Инженер дома"}
    assert {row["full_name"] for row in pkg.tables["employees"]} == {"Свой сотрудник"}

    emp_id = employees.list_employees()[0].id
    employees_later = EmployeeService(conn, session, clock=lambda: _T1)
    employees_later.update_employee(
        emp_id,
        EmployeeUpdateInput(
            full_name="Свой сотрудник",
            position_id=pos_foreign,
            branch_id=foreign_id,
            department_id=dept_foreign,
            division_id=None,
            employment_type_id=1,
        ),
    )
    pkg2 = sync.build_export_package(direction_id)
    if "employees" in pkg2.tables:
        assert "Свой сотрудник" not in {row["full_name"] for row in pkg2.tables["employees"]}

    conn.close()


def test_reconcile_branches_remains_only_source_of_foreign_branches(
    tmp_path: Path,
) -> None:
    conn, session = _open(tmp_path)
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    _identity(conn, session, directories).set_home_branch(new_branch_name="Домашний")
    assert len(directories.list_branches(active_only=False)) == 1

    foreign_external_id = str(uuid.uuid4())
    importer = DirectorySyncImportService(conn, session, clock=lambda: _T1)
    importer.apply_package(
        DirectorySyncPackage(
            tables={
                "branches": [
                    {
                        "external_id": foreign_external_id,
                        "name": "Импортированный",
                        "is_archived": False,
                        "created_at": _T1,
                        "updated_at": _T1,
                    }
                ]
            }
        )
    )

    names = {b.name for b in directories.list_branches(active_only=False)}
    assert names == {"Домашний", "Импортированный"}
    conn.close()
