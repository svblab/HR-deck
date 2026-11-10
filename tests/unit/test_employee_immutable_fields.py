"""Unit: неизменяемость ФИО и филиала в EmployeeService.update_employee (E1-03)."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.employee import EmployeeCreateInput, EmployeeUpdateInput
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeError, EmployeeService


def _open(tmp_path: Path):
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-11-09T12:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    ds = DirectoryService(conn, session, clock=lambda: "2026-11-09T12:01:00Z")
    branch_a = ds.create_branch("Филиал А")
    branch_b = ds.create_branch("Филиал Б")
    dept = ds.create_department(branch_a, "Департамент А")
    pos = ds.create_position(branch_a, "Инженер А")
    et = ds.create_employment_type("e103_staff", "E103 штат")
    refs = {
        "branch_a": branch_a,
        "branch_b": branch_b,
        "department_id": dept,
        "position_id": pos,
        "employment_type_id": et,
    }
    svc = EmployeeService(conn, session, clock=lambda: "2026-11-09T12:02:00Z")
    return conn, svc, refs


def _create(svc: EmployeeService, refs: dict[str, int], full_name: str = "Иванов Иван") -> int:
    return svc.create_employee(
        EmployeeCreateInput(
            full_name=full_name,
            position_id=refs["position_id"],
            branch_id=refs["branch_a"],
            department_id=refs["department_id"],
            employment_type_id=refs["employment_type_id"],
        )
    )


def _update_kwargs(
    refs: dict[str, int],
    *,
    full_name: str,
    branch_id: int,
    note: str | None = None,
):
    return EmployeeUpdateInput(
        full_name=full_name,
        position_id=refs["position_id"],
        branch_id=branch_id,
        department_id=refs["department_id"],
        employment_type_id=refs["employment_type_id"],
        note=note,
    )


def test_create_records_full_name_and_branch(tmp_path: Path) -> None:
    conn, svc, refs = _open(tmp_path)
    emp_id = _create(svc, refs, "Петров Пётр")
    card = svc.get_employee(emp_id)
    assert card.full_name == "Петров Пётр"
    assert card.branch_id == refs["branch_a"]
    conn.close()


def test_update_rejects_full_name_change(tmp_path: Path) -> None:
    conn, svc, refs = _open(tmp_path)
    emp_id = _create(svc, refs, "Сидоров")
    with pytest.raises(EmployeeError, match="full_name cannot be changed"):
        svc.update_employee(
            emp_id,
            _update_kwargs(refs, full_name="Другое ФИО", branch_id=refs["branch_a"]),
        )
    assert svc.get_employee(emp_id).full_name == "Сидоров"
    conn.close()


def test_update_rejects_branch_change(tmp_path: Path) -> None:
    conn, svc, refs = _open(tmp_path)
    emp_id = _create(svc, refs, "Козлов")
    with pytest.raises(EmployeeError, match="branch_id cannot be changed"):
        svc.update_employee(
            emp_id,
            _update_kwargs(refs, full_name="Козлов", branch_id=refs["branch_b"]),
        )
    assert svc.get_employee(emp_id).branch_id == refs["branch_a"]
    conn.close()


def test_same_name_with_surrounding_spaces_accepted(tmp_path: Path) -> None:
    conn, svc, refs = _open(tmp_path)
    emp_id = _create(svc, refs, "Морозов Алексей")
    svc.update_employee(
        emp_id,
        _update_kwargs(
            refs,
            full_name="  Морозов Алексей  ",
            branch_id=refs["branch_a"],
            note="пробелы по краям",
        ),
    )
    card = svc.get_employee(emp_id)
    assert card.full_name == "Морозов Алексей"
    assert card.note == "пробелы по краям"
    conn.close()


def test_same_values_update_succeeds(tmp_path: Path) -> None:
    conn, svc, refs = _open(tmp_path)
    emp_id = _create(svc, refs, "Васильев")
    svc.update_employee(
        emp_id,
        _update_kwargs(
            refs,
            full_name="Васильев",
            branch_id=refs["branch_a"],
            note="обновление без смены ФИО/филиала",
        ),
    )
    card = svc.get_employee(emp_id)
    assert card.full_name == "Васильев"
    assert card.branch_id == refs["branch_a"]
    assert card.note == "обновление без смены ФИО/филиала"
    rows = conn.execute(
        "SELECT action_type FROM user_action_log WHERE entity_id=?",
        (emp_id,),
    ).fetchall()
    actions = {r[0] for r in rows}
    assert "employee.create" in actions
    assert "employee.update" in actions
    conn.close()
