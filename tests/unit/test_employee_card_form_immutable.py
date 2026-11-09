"""Unit UI: ФИО/филиал неизменяемы на форме после создания (E1-03, ТЗ §9.7.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.employee import EmployeeCreateInput, EmployeeUpdateInput
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeError, EmployeeService
from services.session import SessionState
from tests.fixtures.synthetic import seed_synthetic_org
from ui.employee_card_form import _IMMUTABLE_HINT, EmployeeCardDialog


def _open(tmp_path: Path):
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-11-09T13:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    ids = seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=lambda: "2026-11-09T13:00:00Z")
    directories = DirectoryService(conn, session, clock=lambda: "2026-11-09T13:00:00Z")
    return conn, session, employees, directories, ids, db


def test_create_mode_name_and_branch_editable(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    dialog = EmployeeCardDialog(employees, directories, session, employee_id=None)
    qtbot.addWidget(dialog)
    assert not dialog._name.isReadOnly()
    assert dialog._name.isEnabled()
    assert dialog._branch.isEnabled()
    assert dialog._immutable_hint.isHidden()
    conn.close()


def test_edit_mode_name_readonly_branch_disabled_with_hint(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, ids, _db = _open(tmp_path)
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Карточка Редакт",
            position_id=ids["position_engineer_id"],
            branch_id=ids["branch_id"],
            department_id=ids["department_id"],
            division_id=ids["division_id"],
            employment_type_id=1,
        )
    )
    dialog = EmployeeCardDialog(employees, directories, session, employee_id=emp_id)
    qtbot.addWidget(dialog)
    assert dialog._name.isReadOnly()
    assert not dialog._branch.isEnabled()
    assert not dialog._immutable_hint.isHidden()
    assert _IMMUTABLE_HINT in dialog._immutable_hint.text()
    assert "недоступны для правки после создания" in dialog._immutable_hint.text()
    conn.close()


def test_immutable_flags_survive_archive_restore_cycle(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, ids, _db = _open(tmp_path)
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Архив Цикл",
            position_id=ids["position_engineer_id"],
            branch_id=ids["branch_id"],
            department_id=ids["department_id"],
            division_id=ids["division_id"],
            employment_type_id=1,
        )
    )
    dialog = EmployeeCardDialog(employees, directories, session, employee_id=emp_id)
    qtbot.addWidget(dialog)
    assert dialog._is_archived is False
    assert dialog._name.isReadOnly()
    assert not dialog._branch.isEnabled()

    dialog._is_archived = True
    dialog._apply_archived_state()
    assert dialog._name.isReadOnly()
    assert not dialog._branch.isEnabled()

    dialog._is_archived = False
    dialog._apply_archived_state()
    assert dialog._name.isReadOnly()
    assert not dialog._branch.isEnabled()
    assert dialog._name.isEnabled()
    conn.close()


def test_can_manage_false_keeps_all_widgets_disabled(qtbot, tmp_path: Path) -> None:
    conn, admin, _employees_admin, _directories, ids, db = _open(tmp_path)
    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-11-09T13:05:00Z"
    )
    observer_id = mgr.create_account(
        login="obs1", password="ObsPass-1", role=RoleCode.OBSERVER
    )
    observer = SessionState(
        account_id=observer_id,
        login="obs1",
        role=RoleCode.OBSERVER,
        master_key=admin.master_key,
    )
    employees = EmployeeService(conn, observer, clock=lambda: "2026-11-09T13:06:00Z")
    directories = DirectoryService(conn, observer, clock=lambda: "2026-11-09T13:06:00Z")
    emp_id = ids["employee_a_id"]
    dialog = EmployeeCardDialog(employees, directories, observer, employee_id=emp_id)
    qtbot.addWidget(dialog)
    for widget in (
        dialog._name,
        dialog._position,
        dialog._branch,
        dialog._department,
        dialog._division,
        dialog._employment,
        dialog._note,
    ):
        assert not widget.isEnabled()
    conn.close()


def test_service_rejection_on_name_change_via_update(qtbot, tmp_path: Path) -> None:
    """UI flags are advisory; service rejects changed full_name (setText is not blocked)."""
    conn, session, employees, directories, ids, _db = _open(tmp_path)
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Сервис Отказ",
            position_id=ids["position_engineer_id"],
            branch_id=ids["branch_id"],
            department_id=ids["department_id"],
            division_id=ids["division_id"],
            employment_type_id=1,
        )
    )
    with pytest.raises(EmployeeError, match="full_name cannot be changed"):
        employees.update_employee(
            emp_id,
            EmployeeUpdateInput(
                full_name="Другое",
                position_id=ids["position_engineer_id"],
                branch_id=ids["branch_id"],
                department_id=ids["department_id"],
                division_id=ids["division_id"],
                employment_type_id=1,
            ),
        )
    dialog = EmployeeCardDialog(employees, directories, session, employee_id=emp_id)
    qtbot.addWidget(dialog)
    dialog._name.setText("Другое через setText")
    assert dialog._name.text() == "Другое через setText"
    assert dialog._name.isReadOnly()
    conn.close()
