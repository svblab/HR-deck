"""EPIC-020 020-D: transport import validation gate (no writes / no apply)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from data.directories import BranchRepository, PositionRepository
from data.employees import EmployeeRepository
from domain.employee import EmployeeCreateInput
from domain.permissions import RoleCode
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.session import SessionState
from services.transport_import_validation import (
    FreshnessClass,
    TransportImportValidationService,
    ValidationDisposition,
)
from services.transport_keys import TransportKeyStore
from services.transport_receive import DecryptedTransportPackage

_T0 = "2026-09-25T12:00:00Z"


def _admin_open(tmp_path: Path, *, name: str = "app.db"):
    db = tmp_path / name
    conn, session, _code = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    store = TransportKeyStore(conn, clock=lambda: _T0)
    return conn, session, store


def _ensure_inbound_direction(store: TransportKeyStore, conn) -> int:
    local = store.ensure_local_installation(display_label="Local")
    store.generate_local_signing_identity()
    store.generate_local_bootstrap_identity()
    peer_installation_id = str(uuid.uuid4())
    peer_id = store.register_peer_trust(
        peer_installation_id=peer_installation_id,
        display_label="Peer",
        signing_public_key=b"\x01" * 32,
        signing_fingerprint="peer-sign-fp",
        bootstrap_public_key=b"\x02" * 32,
        bootstrap_fingerprint="peer-boot-fp",
    )
    # Inbound: peer is sender, local is recipient.
    direction = store.ensure_direction(
        sender_installation_id=peer_installation_id,
        recipient_installation_id=local.installation_id,
        peer_trust_id=peer_id,
    )
    conn.commit()
    return direction.id


def _decrypted(
    *,
    direction_id: int,
    sequence: int,
    package_id: str,
    tables: dict[str, list[dict[str, object]]] | None = None,
    payload: bytes | None = None,
) -> DecryptedTransportPackage:
    body = payload if payload is not None else json.dumps(tables or {}).encode("utf-8")
    return DecryptedTransportPackage(
        payload=body,
        sender_installation_id="sender",
        recipient_installation_id="recipient",
        direction_id=direction_id,
        sequence=sequence,
        package_id=package_id,
        envelope_key_id="bootstrap",
        next_wk_key_id=str(uuid.uuid4()),
        next_wk_material=b"\x03" * 32,
    )


def _snapshot_transport(conn, direction_id: int) -> tuple[int, int, int]:
    row = conn.execute(
        "SELECT accepted_sequence, current_wk_id FROM transport_direction_state WHERE id = ?",
        (direction_id,),
    ).fetchone()
    packages = conn.execute(
        "SELECT COUNT(*) FROM transport_package_records WHERE direction_id = ?",
        (direction_id,),
    ).fetchone()[0]
    return int(row[0]), int(packages), 0 if row[1] is None else int(row[1])


def _count_dir_rows(conn) -> int:
    total = 0
    for table in ("branches", "departments", "divisions", "positions", "employees"):
        total += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return total


def test_classify_exact_replay(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    package_id = str(uuid.uuid4())
    store.record_package_acceptance(
        direction_id=direction_id,
        package_id=package_id,
        sequence=1,
        envelope_key_id="bootstrap",
        next_wk=None,
        accepted_sequence=1,
    )
    conn.commit()
    before = _snapshot_transport(conn, direction_id)
    before_rows = _count_dir_rows(conn)

    svc = TransportImportValidationService(conn, session, store=store)
    result = svc.validate_package(
        _decrypted(direction_id=direction_id, sequence=1, package_id=package_id)
    )
    assert result.freshness is FreshnessClass.REPLAY
    assert result.disposition is ValidationDisposition.REPLAY
    assert result.directory_plan is None
    assert result.employee_plan is None
    assert _snapshot_transport(conn, direction_id) == before
    assert _count_dir_rows(conn) == before_rows
    conn.close()


def test_classify_stale_sequence(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    store.record_package_acceptance(
        direction_id=direction_id,
        package_id=str(uuid.uuid4()),
        sequence=3,
        envelope_key_id="bootstrap",
        next_wk=None,
        accepted_sequence=3,
    )
    conn.commit()
    before = _snapshot_transport(conn, direction_id)

    svc = TransportImportValidationService(conn, session, store=store)
    result = svc.validate_package(
        _decrypted(
            direction_id=direction_id,
            sequence=2,
            package_id=str(uuid.uuid4()),
        )
    )
    assert result.freshness is FreshnessClass.STALE
    assert result.disposition is ValidationDisposition.REJECTED
    assert "stale" in result.reject_reasons[0]
    assert _snapshot_transport(conn, direction_id) == before
    conn.close()


def test_classify_valid_new_empty_package(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    before = _snapshot_transport(conn, direction_id)
    before_rows = _count_dir_rows(conn)

    svc = TransportImportValidationService(conn, session, store=store)
    result = svc.validate_package(
        _decrypted(
            direction_id=direction_id,
            sequence=1,
            package_id=str(uuid.uuid4()),
            tables={},
        )
    )
    assert result.freshness is FreshnessClass.NEW
    assert result.disposition is ValidationDisposition.READY_FOR_APPLY
    assert result.directory_plan is not None and result.directory_plan.is_clean
    assert result.employee_plan is not None and result.employee_plan.is_clean
    assert _snapshot_transport(conn, direction_id) == before
    assert _count_dir_rows(conn) == before_rows
    conn.close()


def test_directory_reject_blocks_employee_acceptance(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    branch_id = directories.create_branch("Филиал")
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
    before_rows = _count_dir_rows(conn)
    before_tx = _snapshot_transport(conn, direction_id)

    tables = {
        "branches": [
            {
                "id": branch_id,
                "external_id": branch.external_id,
                "name": branch.name,
                "is_archived": False,
                "created_at": _T0,
                "updated_at": _T0,
            }
        ],
        "positions": [
            {
                "id": pos_id,
                "external_id": pos.external_id,
                "branch_external_id": branch.external_id,
                "name": pos.name,
                "department_required": True,
                "division_required": False,
                "is_archived": False,
                "created_at": _T0,
                "updated_at": _T0,
            }
        ],
        "employees": [],
    }
    svc = TransportImportValidationService(conn, session, store=store)
    result = svc.validate_package(
        _decrypted(
            direction_id=direction_id,
            sequence=1,
            package_id=str(uuid.uuid4()),
            tables=tables,
        )
    )
    assert result.freshness is FreshnessClass.NEW
    assert result.disposition is ValidationDisposition.REJECTED
    assert result.directory_plan is not None
    assert not result.directory_plan.is_clean
    assert result.employee_plan is None  # whole-package: employee not accepted
    still = PositionRepository(conn).get(pos_id)
    assert still is not None
    assert still.department_required is False
    assert _count_dir_rows(conn) == before_rows
    assert _snapshot_transport(conn, direction_id) == before_tx
    conn.close()


def test_employee_conflict_rejects_without_writes(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    branch_id = directories.create_branch("Филиал")
    dept_id = directories.create_department(branch_id, "Деп")
    div_id = directories.create_division(branch_id, dept_id, "Отдел")
    pos_id = directories.create_position(branch_id, "Инженер")
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Иванов Иван Иванович",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=dept_id,
            division_id=div_id,
            employment_type_id=1,
        )
    )
    record = EmployeeRepository(conn).get(emp_id)
    branch = BranchRepository(conn).get(branch_id)
    pos = PositionRepository(conn).get(pos_id)
    from data.directories import DepartmentRepository, DivisionRepository

    dept = DepartmentRepository(conn).get(dept_id)
    div = DivisionRepository(conn).get(div_id)
    assert record and branch and pos and dept and div
    before_rows = _count_dir_rows(conn)

    tables = {
        "employees": [
            {
                "id": 1,
                "external_id": record.external_id,
                "full_name": "Петров Пётр Петрович",
                "position_external_id": pos.external_id,
                "branch_external_id": branch.external_id,
                "department_external_id": dept.external_id,
                "division_external_id": div.external_id,
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
    svc = TransportImportValidationService(conn, session, store=store)
    result = svc.validate_package(
        _decrypted(
            direction_id=direction_id,
            sequence=1,
            package_id=str(uuid.uuid4()),
            tables=tables,
        )
    )
    assert result.disposition is ValidationDisposition.REJECTED
    assert result.employee_plan is not None
    assert result.employee_plan.conflicts
    still = EmployeeRepository(conn).get(emp_id)
    assert still is not None
    assert still.full_name == "Иванов Иван Иванович"
    assert _count_dir_rows(conn) == before_rows
    conn.close()


def test_employee_low_confidence_pending_confirmation(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    branch_id = directories.create_branch("Филиал")
    dept_id = directories.create_department(branch_id, "Деп")
    div_id = directories.create_division(branch_id, dept_id, "Отдел")
    pos_id = directories.create_position(branch_id, "Инженер")
    employees.create_employee(
        EmployeeCreateInput(
            full_name="Сидоров Сидор Сидорович",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=dept_id,
            division_id=div_id,
            employment_type_id=1,
        )
    )
    branch = BranchRepository(conn).get(branch_id)
    pos = PositionRepository(conn).get(pos_id)
    from data.directories import DepartmentRepository, DivisionRepository

    dept = DepartmentRepository(conn).get(dept_id)
    div = DivisionRepository(conn).get(div_id)
    assert branch and pos and dept and div
    before_rows = _count_dir_rows(conn)

    # New external_id, same FIO+org → LOW confidence name match.
    tables = {
        "employees": [
            {
                "id": 1,
                "external_id": str(uuid.uuid4()),
                "full_name": "Сидоров Сидор Сидорович",
                "position_external_id": pos.external_id,
                "branch_external_id": branch.external_id,
                "department_external_id": dept.external_id,
                "division_external_id": div.external_id,
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
    svc = TransportImportValidationService(conn, session, store=store)
    result = svc.validate_package(
        _decrypted(
            direction_id=direction_id,
            sequence=1,
            package_id=str(uuid.uuid4()),
            tables=tables,
        )
    )
    assert result.disposition is ValidationDisposition.PENDING_CONFIRMATION
    assert result.confirmation_reasons
    assert _count_dir_rows(conn) == before_rows
    conn.close()


def test_observer_rejected(tmp_path: Path) -> None:
    conn, session, store = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    observer = SessionState(
        account_id=session.account_id,
        login="obs",
        role=RoleCode.OBSERVER,
        master_key=session.master_key,
        locked=False,
    )
    from services.authorization import AuthorizationError

    svc = TransportImportValidationService(conn, observer, store=store)
    with pytest.raises(AuthorizationError):
        svc.validate_package(
            _decrypted(
                direction_id=direction_id,
                sequence=1,
                package_id=str(uuid.uuid4()),
            )
        )
    conn.close()
