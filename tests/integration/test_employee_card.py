"""Integration: карточка сотрудника CRUD, RBAC, sensitive, audit (EPIC-005)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import Connection
from domain.employee import EmployeeCreateInput, EmployeeUpdateInput, SensitiveEmployeeInput
from domain.permissions import RoleCode
from domain.sensitive import SENSITIVE_MASK
from services.account_management import AccountManagementService
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeError, EmployeeService
from services.session import SessionState
from tests.fixtures.synthetic import seed_synthetic_org


def _open_db(tmp_path: Path) -> tuple[Connection, SessionState, Path]:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-26T12:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return conn, session, db


def _hr_session(conn: Connection, admin: SessionState, db: Path) -> SessionState:
    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-08-26T12:01:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    return SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin.master_key,
    )


def _seed_directories(
    conn: Connection, session: SessionState
) -> dict[str, int]:
    ds = DirectoryService(conn, session, clock=lambda: "2026-08-26T13:00:00Z")
    branch_id = ds.create_branch("Филиал Тест")
    dept_id = ds.create_department(branch_id, "Департамент QA")
    div_id = ds.create_division(dept_id, "Отдел A")
    pos_id = ds.create_position("Инженер")
    et_id = ds.create_employment_type("test_staff", "Тестовый штат")
    return {
        "branch_id": branch_id,
        "department_id": dept_id,
        "division_id": div_id,
        "position_id": pos_id,
        "employment_type_id": et_id,
    }


@pytest.mark.acceptance
def test_create_employee_with_required_fields(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    refs = _seed_directories(conn, session)
    svc = EmployeeService(conn, session, clock=lambda: "2026-08-26T14:00:00Z")
    emp_id = svc.create_employee(
        EmployeeCreateInput(
            full_name="Иванов Иван Иванович",
            position_id=refs["position_id"],
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            division_id=refs["division_id"],
            employment_type_id=refs["employment_type_id"],
            note="тест",
        )
    )
    card = svc.get_employee(emp_id)
    assert card.full_name == "Иванов Иван Иванович"
    assert card.note == "тест"
    row = conn.execute(
        "SELECT hire_date, contacts FROM employees WHERE id = ?", (emp_id,)
    ).fetchone()
    assert row[0] is None and row[1] is None
    conn.close()


@pytest.mark.acceptance
def test_duplicate_full_name_allowed_by_id(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    refs = _seed_directories(conn, session)
    svc = EmployeeService(conn, session, clock=lambda: "2026-08-26T14:10:00Z")
    a = svc.create_employee(
        EmployeeCreateInput(
            full_name="Петров Петр",
            position_id=refs["position_id"],
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            employment_type_id=refs["employment_type_id"],
        )
    )
    b = svc.create_employee(
        EmployeeCreateInput(
            full_name="Петров Петр",
            position_id=refs["position_id"],
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            employment_type_id=refs["employment_type_id"],
        )
    )
    assert a != b
    conn.close()


@pytest.mark.acceptance
def test_search_disambiguates_same_full_name(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    refs = _seed_directories(conn, session)
    ds = DirectoryService(conn, session, clock=lambda: "2026-08-26T14:15:00Z")
    pos2 = ds.create_position("Аналитик")
    svc = EmployeeService(conn, session, clock=lambda: "2026-08-26T14:16:00Z")
    svc.create_employee(
        EmployeeCreateInput(
            full_name="Сидоров",
            position_id=refs["position_id"],
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            employment_type_id=refs["employment_type_id"],
        )
    )
    svc.create_employee(
        EmployeeCreateInput(
            full_name="Сидоров",
            position_id=pos2,
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            employment_type_id=refs["employment_type_id"],
        )
    )
    hits = svc.search_by_name("Сид")
    assert len(hits) == 2
    positions = {h.position_name for h in hits}
    assert positions == {"Инженер", "Аналитик"}
    conn.close()


@pytest.mark.acceptance
def test_hr_sees_masked_sensitive_admin_sees_full(tmp_path: Path) -> None:
    conn, admin, db = _open_db(tmp_path)
    refs = _seed_directories(conn, admin)
    admin_svc = EmployeeService(conn, admin, clock=lambda: "2026-08-26T14:20:00Z")
    emp_id = admin_svc.create_employee(
        EmployeeCreateInput(
            full_name="Sensitive Test",
            position_id=refs["position_id"],
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            employment_type_id=refs["employment_type_id"],
        )
    )
    admin_svc.update_sensitive_fields(
        emp_id,
        SensitiveEmployeeInput(
            home_address="г. Тестовск",
            social_insurance_number="000-111",
        ),
    )
    hr = _hr_session(conn, admin, db)
    hr_svc = EmployeeService(conn, hr, clock=lambda: "2026-08-26T14:21:00Z")
    hr_card = hr_svc.get_employee(emp_id)
    assert hr_card.sensitive_fields_masked is True
    assert hr_card.home_address == SENSITIVE_MASK
    assert "Тестовск" not in (hr_card.home_address or "")

    admin_card = admin_svc.get_employee(emp_id)
    assert admin_card.sensitive_fields_masked is False
    assert admin_card.home_address == "г. Тестовск"

    audit = conn.execute(
        "SELECT action_type FROM user_action_log WHERE entity_id=? AND action_type=?",
        (emp_id, "employee.view_sensitive"),
    ).fetchall()
    assert len(audit) >= 1
    conn.close()


@pytest.mark.acceptance
def test_hr_cannot_edit_sensitive_fields(tmp_path: Path) -> None:
    conn, admin, db = _open_db(tmp_path)
    refs = _seed_directories(conn, admin)
    admin_svc = EmployeeService(conn, admin, clock=lambda: "2026-08-26T14:30:00Z")
    emp_id = admin_svc.create_employee(
        EmployeeCreateInput(
            full_name="No Sensitive Edit",
            position_id=refs["position_id"],
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            employment_type_id=refs["employment_type_id"],
        )
    )
    hr = _hr_session(conn, admin, db)
    hr_svc = EmployeeService(conn, hr, clock=lambda: "2026-08-26T14:31:00Z")
    with pytest.raises(AuthorizationError):
        hr_svc.update_sensitive_fields(
            emp_id, SensitiveEmployeeInput(home_address="x")
        )
    conn.close()


@pytest.mark.acceptance
def test_archived_directory_rejected_for_new_employee(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    refs = _seed_directories(conn, session)
    ds = DirectoryService(conn, session, clock=lambda: "2026-08-26T14:40:00Z")
    ds.archive_position(refs["position_id"])
    svc = EmployeeService(conn, session, clock=lambda: "2026-08-26T14:41:00Z")
    with pytest.raises(EmployeeError, match="archived position"):
        svc.create_employee(
            EmployeeCreateInput(
                full_name="Fail",
                position_id=refs["position_id"],
                branch_id=refs["branch_id"],
                department_id=refs["department_id"],
                employment_type_id=refs["employment_type_id"],
            )
        )
    conn.close()


@pytest.mark.acceptance
def test_update_employee_and_audit(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    refs = _seed_directories(conn, session)
    svc = EmployeeService(conn, session, clock=lambda: "2026-08-26T14:50:00Z")
    emp_id = svc.create_employee(
        EmployeeCreateInput(
            full_name="Before",
            position_id=refs["position_id"],
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            employment_type_id=refs["employment_type_id"],
        )
    )
    svc.update_employee(
        emp_id,
        EmployeeUpdateInput(
            full_name="After",
            position_id=refs["position_id"],
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            employment_type_id=refs["employment_type_id"],
        ),
    )
    assert svc.get_employee(emp_id).full_name == "After"
    rows = conn.execute(
        "SELECT action_type FROM user_action_log WHERE entity_id=?",
        (emp_id,),
    ).fetchall()
    actions = {r[0] for r in rows}
    assert "employee.create" in actions
    assert "employee.update" in actions
    conn.close()


@pytest.mark.acceptance
def test_directory_rename_preserves_employee_links(tmp_path: Path) -> None:
    conn, session, _db = _open_db(tmp_path)
    ids = seed_synthetic_org(conn)
    refs = {
        "position_id": ids["position_engineer_id"],
        "branch_id": ids["branch_id"],
        "department_id": ids["department_id"],
        "division_id": ids["division_id"],
        "employment_type_id": 1,
    }
    svc = EmployeeService(conn, session, clock=lambda: "2026-08-26T15:00:00Z")
    emp_id = svc.create_employee(
        EmployeeCreateInput(
            full_name="Link Test",
            position_id=refs["position_id"],
            branch_id=refs["branch_id"],
            department_id=refs["department_id"],
            division_id=refs["division_id"],
            employment_type_id=refs["employment_type_id"],
        )
    )
    ds = DirectoryService(conn, session, clock=lambda: "2026-08-26T15:01:00Z")
    ds.rename_branch(refs["branch_id"], "Новое имя филиала")
    card = svc.get_employee(emp_id)
    assert card.branch_id == refs["branch_id"]
    conn.close()
