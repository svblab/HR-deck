"""UI: форма карточки сотрудника (ТЗ §3.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.session import SessionState
from tests.fixtures.synthetic import seed_synthetic_org
from ui.employee_card_form import EmployeeCardDialog


def _capture_warnings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    seen: list[tuple[object, ...]] = []

    def _warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        seen.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", _warning)
    return seen


def _open(tmp_path: Path):
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-27T10:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    ids = seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=lambda: "2026-08-27T10:00:00Z")
    directories = DirectoryService(conn, session, clock=lambda: "2026-08-27T10:00:00Z")
    return conn, session, employees, directories, ids, db


def test_form_rejects_missing_required_fields(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    warnings = _capture_warnings(monkeypatch)
    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    dialog._submit()
    assert dialog.result() != QDialog.DialogCode.Accepted
    text = " ".join(str(item) for item in warnings)
    assert "ФИО" in text
    assert "должность" in text
    conn.close()


def test_similar_names_show_position_and_hire_date(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    dialog._name.setText("Иванов Иван Иванович")
    dialog._refresh_similar()
    assert not dialog._similar.isHidden()
    hint = dialog._similar.text()
    assert "Инженер" in hint
    assert "Аналитик" in hint
    assert "2024-01-15" in hint
    conn.close()


def test_sensitive_fields_hidden_for_hr(qtbot, tmp_path: Path) -> None:
    conn, admin, _employees_admin, _directories, _ids, db = _open(tmp_path)
    mgr = AccountManagementService(
        conn, admin, db_path=db, clock=lambda: "2026-08-27T10:05:00Z"
    )
    hr_id = mgr.create_account(login="hr1", password="HrPass-1", role=RoleCode.HR_EMPLOYEE)
    hr = SessionState(
        account_id=hr_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin.master_key,
    )
    employees = EmployeeService(conn, hr, clock=lambda: "2026-08-27T10:06:00Z")
    directories_hr = DirectoryService(conn, hr, clock=lambda: "2026-08-27T10:06:00Z")
    dialog = EmployeeCardDialog(employees, directories_hr, hr)
    qtbot.addWidget(dialog)
    assert dialog._home.isHidden()
    assert dialog._insurance.isHidden()
    conn.close()


def _select_combo(combo, entity_id: int | None) -> None:  # noqa: ANN001
    idx = combo.findData(entity_id)
    assert idx >= 0, f"id {entity_id} not in combo"
    combo.setCurrentIndex(idx)


def _division_names(dialog: EmployeeCardDialog) -> list[str]:
    combo = dialog._division
    return [
        combo.itemText(i)
        for i in range(combo.count())
        if combo.itemData(i) is not None
    ]


@pytest.mark.acceptance
def test_employee_card_division_list_filters_by_department_or_branch_direct(
    qtbot, tmp_path: Path
) -> None:
    """ADR-0008: без департамента — только отделы филиала; с департаментом — его отделы."""
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_id = directories.create_branch("Филиал Юг")
    dept_id = directories.create_department(branch_id, "Департамент QA")
    directories.create_division(branch_id, dept_id, "Отдел QA")
    directories.create_division(branch_id, None, "Секретариат филиала")

    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    _select_combo(dialog._branch, branch_id)
    dialog._fill_divisions()
    assert "Секретариат филиала" in _division_names(dialog)
    assert "Отдел QA" not in _division_names(dialog)

    _select_combo(dialog._department, dept_id)
    dialog._fill_divisions()
    assert "Отдел QA" in _division_names(dialog)
    assert "Секретариат филиала" not in _division_names(dialog)
    conn.close()


@pytest.mark.acceptance
def test_employee_card_save_without_department_branch_direct_division(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0008: карточка сохраняется без департамента с отделом филиала."""
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_id = directories.create_branch("Филиал Восток")
    pos_id = directories.create_position(branch_id, "Менеджер")
    div_id = directories.create_division(branch_id, None, "Секретариат")

    warnings = _capture_warnings(monkeypatch)
    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    dialog._name.setText("Петров Петр Петрович")
    _select_combo(dialog._branch, branch_id)
    _select_combo(dialog._position, pos_id)
    _select_combo(dialog._employment, 1)
    dialog._fill_divisions()
    _select_combo(dialog._division, div_id)
    dialog._submit()
    assert not warnings
    assert dialog.result() == QDialog.DialogCode.Accepted
    row = conn.execute(
        "SELECT department_id, division_id FROM employees WHERE full_name = ?",
        ("Петров Петр Петрович",),
    ).fetchone()
    assert row == (None, div_id)
    conn.close()


@pytest.mark.acceptance
def test_employee_card_submit_branch_only_no_department_no_division(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0008: branch-only employee saves through form submit."""
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_id = directories.create_branch("Филиал Запад")
    pos_id = directories.create_position(branch_id, "Директор")

    warnings = _capture_warnings(monkeypatch)
    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    dialog._name.setText("Сидоров Сидор Сидорович")
    _select_combo(dialog._branch, branch_id)
    _select_combo(dialog._position, pos_id)
    _select_combo(dialog._employment, 1)
    dialog._submit()
    assert not warnings
    assert dialog.result() == QDialog.DialogCode.Accepted
    row = conn.execute(
        "SELECT department_id, division_id FROM employees WHERE full_name = ?",
        ("Сидоров Сидор Сидорович",),
    ).fetchone()
    assert row == (None, None)
    conn.close()


@pytest.mark.acceptance
def test_employee_card_submit_department_only_no_division(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0008: department without child divisions saves through form submit."""
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_id = directories.create_branch("Филиал Центр")
    dept_id = directories.create_department(branch_id, "Департамент без отделов")
    pos_id = directories.create_position(branch_id, "Руководитель")

    warnings = _capture_warnings(monkeypatch)
    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    dialog._name.setText("Козлов Козел Козлович")
    _select_combo(dialog._branch, branch_id)
    _select_combo(dialog._department, dept_id)
    _select_combo(dialog._position, pos_id)
    _select_combo(dialog._employment, 1)
    dialog._submit()
    assert not warnings
    assert dialog.result() == QDialog.DialogCode.Accepted
    row = conn.execute(
        "SELECT department_id, division_id FROM employees WHERE full_name = ?",
        ("Козлов Козел Козлович",),
    ).fetchone()
    assert row == (dept_id, None)
    conn.close()


def test_employee_card_submit_missing_division_no_longer_blocks(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_id = directories.create_branch("Филиал Север")
    pos_id = directories.create_position(branch_id, "Аналитик")

    warnings = _capture_warnings(monkeypatch)
    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    dialog._name.setText("Волков Волк Волкович")
    _select_combo(dialog._branch, branch_id)
    _select_combo(dialog._position, pos_id)
    _select_combo(dialog._employment, 1)
    assert dialog._missing_required() == []
    dialog._submit()
    assert not warnings
    text = " ".join(str(item) for item in warnings)
    assert "отдел" not in text
    assert dialog.result() == QDialog.DialogCode.Accepted
    conn.close()


@pytest.mark.acceptance
def test_employee_card_position_department_required_blocks_submit(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_id = directories.create_branch("Филиал Юг")
    pos_id = directories.create_position(branch_id, "Бухгалтер", department_required=True)

    warnings = _capture_warnings(monkeypatch)
    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    dialog._name.setText("Смирнов Смирн Смирнович")
    _select_combo(dialog._branch, branch_id)
    _select_combo(dialog._position, pos_id)
    _select_combo(dialog._employment, 1)
    dialog._submit()
    assert dialog.result() != QDialog.DialogCode.Accepted
    text = " ".join(str(item) for item in warnings)
    assert "департамент" in text
    conn.close()


@pytest.mark.acceptance
def test_employee_card_shows_org_review_banner_for_flagged_employee(
    qtbot, tmp_path: Path
) -> None:
    from domain.employee import EmployeeCreateInput

    conn, session, employees, directories, ids, _db = _open(tmp_path)
    pos_id = directories.create_position(ids["branch_id"], "Инженер", department_required=True)
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Орлов Орел Орлович",
            position_id=pos_id,
            branch_id=ids["branch_id"],
            department_id=ids["department_id"],
            division_id=ids["division_id"],
            employment_type_id=1,
        )
    )
    directories.apply_position_requirement_change(
        pos_id,
        department_required=True,
        division_required=False,
        reset_violations=True,
    )
    conn.execute(
        "UPDATE employees SET needs_org_review = 1 WHERE id = ?",
        (emp_id,),
    )

    dialog = EmployeeCardDialog(
        employees, directories, session, employee_id=emp_id
    )
    qtbot.addWidget(dialog)
    assert not dialog._org_review.isHidden()
    assert "Требует внимания" in dialog._org_review.text()
    conn.close()


@pytest.mark.acceptance
def test_employee_card_position_without_requirements_unblocks_submit(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_id = directories.create_branch("Филиал Запад")
    strict_id = directories.create_position(branch_id, "Строгая", department_required=True)
    loose_id = directories.create_position(branch_id, "Свободная")

    warnings = _capture_warnings(monkeypatch)
    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    dialog._name.setText("Медведев Медведь Медведевич")
    _select_combo(dialog._branch, branch_id)
    _select_combo(dialog._position, strict_id)
    _select_combo(dialog._employment, 1)
    dialog._submit()
    assert dialog.result() != QDialog.DialogCode.Accepted

    warnings.clear()
    _select_combo(dialog._position, loose_id)
    dialog._submit()
    assert not warnings
    assert dialog.result() == QDialog.DialogCode.Accepted
    conn.close()


def _position_names(dialog: EmployeeCardDialog) -> list[str]:
    combo = dialog._position
    return [
        combo.itemText(i)
        for i in range(combo.count())
        if combo.itemData(i) is not None
    ]


@pytest.mark.acceptance
def test_employee_card_position_list_filtered_by_branch(qtbot, tmp_path: Path) -> None:
    """ADR-0010: должности в карточке фильтруются по выбранному филиалу."""
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_a = directories.create_branch("Филиал Альфа")
    branch_b = directories.create_branch("Филиал Бета")
    directories.create_position(branch_a, "Инженер Альфа")
    directories.create_position(branch_b, "Инженер Бета")

    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    assert _position_names(dialog) == []

    _select_combo(dialog._branch, branch_a)
    assert _position_names(dialog) == ["Инженер Альфа"]

    _select_combo(dialog._branch, branch_b)
    assert _position_names(dialog) == ["Инженер Бета"]
    conn.close()


@pytest.mark.acceptance
def test_employee_card_branch_change_clears_position(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_a = directories.create_branch("Филиал 1")
    branch_b = directories.create_branch("Филиал 2")
    pos_a = directories.create_position(branch_a, "Должность 1")
    directories.create_position(branch_b, "Должность 2")

    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    _select_combo(dialog._branch, branch_a)
    _select_combo(dialog._position, pos_a)
    assert dialog._position.currentData() == pos_a

    _select_combo(dialog._branch, branch_b)
    assert dialog._position.currentData() is None
    assert dialog._position.currentText() == "Должность"
    conn.close()


@pytest.mark.acceptance
def test_employee_card_existing_employee_lists_all_branch_positions(
    qtbot, tmp_path: Path
) -> None:
    from domain.employee import EmployeeCreateInput

    conn, session, employees, directories, _ids, _db = _open(tmp_path)
    branch_id = directories.create_branch("Филиал Восток")
    pos_a = directories.create_position(branch_id, "Архивариус")
    directories.create_position(branch_id, "Секретарь")
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Сидоров Сидор Сидорович",
            position_id=pos_a,
            branch_id=branch_id,
            department_id=None,
            division_id=None,
            employment_type_id=1,
        )
    )

    dialog = EmployeeCardDialog(
        employees, directories, session, employee_id=emp_id
    )
    qtbot.addWidget(dialog)
    assert dialog._branch.currentData() == branch_id
    assert dialog._position.currentData() == pos_a
    position_names = {
        dialog._position.itemText(i) for i in range(dialog._position.count())
    }
    assert position_names == {"Должность", "Архивариус", "Секретарь"}
    conn.close()

