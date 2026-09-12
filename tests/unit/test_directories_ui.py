"""UI acceptance: справочники оргструктуры (EPIC-004 UI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTabWidget,
)

from domain.employee import EmployeeCreateInput
from domain.permissions import RoleCode
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.session import SessionState
from ui.directories_dialog import DirectoriesDialog
from ui.employee_card_form import EmployeeCardDialog
from ui.main_window import MainWindow

_AS_OF = "2026-09-07T12:00:00Z"


def _fail_on_warning(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
    raise AssertionError(f"unexpected QMessageBox.warning: {args}")


def _session_for_role(
    conn: object,
    admin: SessionState,
    db: Path,
    clock,  # noqa: ANN001
    role: RoleCode,
) -> SessionState:
    if role is RoleCode.ADMINISTRATOR:
        return admin
    mgr = AccountManagementService(conn, admin, db_path=db, clock=clock)
    if role is RoleCode.HR_EMPLOYEE:
        account_id = mgr.create_account(
            login="hr1", password="HrPass-1", role=role
        )
        login = "hr1"
    else:
        account_id = mgr.create_account(
            login="obs1", password="ObsPass-1", role=role
        )
        login = "obs1"
    return SessionState(
        account_id=account_id,
        login=login,
        role=role,
        master_key=admin.master_key,
    )


def _open_empty_db(tmp_path: Path) -> tuple[object, SessionState, Path]:
    clock = lambda: _AS_OF  # noqa: E731
    db = tmp_path / "app.db"
    conn, admin, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    return conn, admin, db


def _select_combo(combo: QComboBox, entity_id: int) -> None:
    idx = combo.findData(entity_id)
    assert idx >= 0, f"id {entity_id} not in {combo.objectName()}"
    combo.setCurrentIndex(idx)


def _click(qtbot, btn: QPushButton | None) -> None:
    assert btn is not None and btn.isEnabled()
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)


def _tab_index(dlg: DirectoriesDialog, title: str) -> int:
    tabs = dlg.findChild(QTabWidget, "directoriesTabs")
    assert tabs is not None
    for i in range(tabs.count()):
        if tabs.tabText(i) == title:
            return i
    raise AssertionError(f"tab {title!r} not found")


def _create_chain_via_dialog(
    qtbot,
    dlg: DirectoriesDialog,
    directories: DirectoryService,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    prompts = iter(
        [
            "Филиал Альфа",
            "Департамент HR",
            "Отдел платформы",
            "Инженер",
        ]
    )
    monkeypatch.setattr(
        "ui.directories_dialog._prompt_text",
        lambda *_a, **_k: (next(prompts), True),
    )
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)

    branch_btn = dlg.findChild(QPushButton, "directoriesBranchCreateBtn")
    _click(qtbot, branch_btn)
    branch_id = directories.list_branches(active_only=True)[0].id

    tabs = dlg.findChild(QTabWidget, "directoriesTabs")
    assert tabs is not None
    tabs.setCurrentIndex(_tab_index(dlg, "Департаменты"))
    dept_parent = dlg.findChild(QComboBox, "directoriesDepartmentParent")
    assert dept_parent is not None
    _select_combo(dept_parent, branch_id)
    dept_btn = dlg.findChild(QPushButton, "directoriesDepartmentCreateBtn")
    _click(qtbot, dept_btn)
    dept_id = directories.list_departments(branch_id=branch_id, active_only=True)[0].id

    tabs.setCurrentIndex(_tab_index(dlg, "Отделы"))
    div_branch = dlg.findChild(QComboBox, "directoriesDivisionExtraParent")
    div_dept = dlg.findChild(QComboBox, "directoriesDivisionParent")
    assert div_branch is not None and div_dept is not None
    _select_combo(div_branch, branch_id)
    _select_combo(div_dept, dept_id)
    div_btn = dlg.findChild(QPushButton, "directoriesDivisionCreateBtn")
    _click(qtbot, div_btn)
    div_id = directories.list_divisions(department_id=dept_id, active_only=True)[0].id

    tabs.setCurrentIndex(_tab_index(dlg, "Должности"))
    pos_btn = dlg.findChild(QPushButton, "directoriesPositionCreateBtn")
    _click(qtbot, pos_btn)
    pos_id = directories.list_positions(active_only=True)[0].id

    return {
        "branch_id": branch_id,
        "department_id": dept_id,
        "division_id": div_id,
        "position_id": pos_id,
    }


def _combo_has_active_item(combo: QComboBox, name: str) -> bool:
    for i in range(combo.count()):
        if combo.itemText(i) == name and combo.itemData(i) is not None:
            return True
    return False


@pytest.mark.acceptance
@pytest.mark.parametrize("role", [RoleCode.ADMINISTRATOR, RoleCode.HR_EMPLOYEE])
def test_directories_dialog_populates_employee_card_combos(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: RoleCode
) -> None:
    """TESTING §5.2 item 0: пустая БД → Справочники → карточка сотрудника."""
    conn, admin, db = _open_empty_db(tmp_path)
    clock = lambda: _AS_OF  # noqa: E731
    session = _session_for_role(conn, admin, db, clock, role)
    directories = DirectoryService(conn, session, clock=clock)
    employees = EmployeeService(conn, session, clock=clock)

    dlg = DirectoriesDialog(directories, session)
    qtbot.addWidget(dlg)
    ids = _create_chain_via_dialog(qtbot, dlg, directories, monkeypatch)
    dlg.close()

    card = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(card)
    assert _combo_has_active_item(card._branch, "Филиал Альфа")
    _select_combo(card._branch, ids["branch_id"])
    assert _combo_has_active_item(card._department, "Департамент HR")
    _select_combo(card._department, ids["department_id"])
    assert _combo_has_active_item(card._division, "Отдел платформы")
    assert _combo_has_active_item(card._position, "Инженер")
    assert card._employment.count() > 1  # seeded employment types from migration

    conn.close()


@pytest.mark.acceptance
def test_directories_hierarchical_tabs_empty_until_parent_selected(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Департаменты/отделы: таблица пуста, пока родитель в комбобоксе не выбран."""
    conn, admin, db = _open_empty_db(tmp_path)
    clock = lambda: _AS_OF  # noqa: E731
    directories = DirectoryService(conn, admin, clock=clock)
    monkeypatch.setattr(
        "ui.directories_dialog._prompt_text",
        lambda *_a, **_k: ("Тест", True),
    )
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)

    branch_id = directories.create_branch("Филиал А")
    dept_id = directories.create_department(branch_id, "Департамент А")
    directories.create_division(dept_id, "Отдел А")
    branch_b_id = directories.create_branch("Филиал Б")
    directories.create_department(branch_b_id, "Департамент Б")

    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    dept_parent = dlg.findChild(QComboBox, "directoriesDepartmentParent")
    dept_table = dlg.findChild(QTableWidget, "directoriesDepartmentTable")
    div_branch = dlg.findChild(QComboBox, "directoriesDivisionExtraParent")
    div_dept = dlg.findChild(QComboBox, "directoriesDivisionParent")
    div_table = dlg.findChild(QTableWidget, "directoriesDivisionTable")
    assert dept_parent is not None and dept_table is not None
    assert div_branch is not None and div_dept is not None and div_table is not None

    assert dept_parent.currentData() is None
    assert dept_table.rowCount() == 0
    assert div_branch.currentData() is None
    assert div_dept.currentData() is None
    assert div_table.rowCount() == 0

    _select_combo(dept_parent, branch_id)
    assert dept_table.rowCount() == 1

    _select_combo(div_branch, branch_id)
    assert div_dept.count() >= 2
    assert div_table.rowCount() == 0

    _select_combo(div_dept, dept_id)
    assert div_table.rowCount() == 1

    dlg.close()
    conn.close()


@pytest.mark.acceptance
def test_observer_directories_dialog_is_view_only(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TESTING §5.2 item 0: Наблюдатель видит справочники, но не редактирует."""
    conn, admin, db = _open_empty_db(tmp_path)
    clock = lambda: _AS_OF  # noqa: E731
    directories_admin = DirectoryService(conn, admin, clock=clock)
    dlg_admin = DirectoriesDialog(directories_admin, admin)
    qtbot.addWidget(dlg_admin)
    monkeypatch = pytest.MonkeyPatch()
    _create_chain_via_dialog(qtbot, dlg_admin, directories_admin, monkeypatch)
    dlg_admin.close()

    obs = _session_for_role(conn, admin, db, clock, RoleCode.OBSERVER)
    window = MainWindow(conn=conn, session=obs, db_path=db)
    qtbot.addWidget(window)
    btn = window.findChild(QPushButton, "directoriesBtn")
    assert btn is not None and btn.isEnabled()

    opened: list[DirectoriesDialog] = []

    def _open_dialog() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, DirectoriesDialog) and widget.isVisible():
                opened.append(widget)
                for prefix in (
                    "directoriesBranch",
                    "directoriesDepartment",
                    "directoriesDivision",
                    "directoriesPosition",
                    "directoriesEmployment",
                ):
                    assert not widget.findChild(
                        QPushButton, f"{prefix}CreateBtn"
                    ).isEnabled()
                    assert not widget.findChild(
                        QPushButton, f"{prefix}RenameBtn"
                    ).isEnabled()
                    assert not widget.findChild(
                        QPushButton, f"{prefix}ArchiveBtn"
                    ).isEnabled()
                    assert not widget.findChild(
                        QPushButton, f"{prefix}RestoreBtn"
                    ).isEnabled()
                table = widget.findChild(QTableWidget, "directoriesBranchTable")
                assert table is not None and table.rowCount() >= 1
                widget.accept()
                return
        raise AssertionError("DirectoriesDialog not visible")

    QTimer.singleShot(0, _open_dialog)
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert opened

    window.close()
    conn.close()


@pytest.mark.acceptance
def test_archived_position_hidden_for_new_employee_kept_on_existing(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Архив должности: не в выпадающем списке новой карточки, сохраняется у сотрудника."""
    conn, admin, db = _open_empty_db(tmp_path)
    clock = lambda: _AS_OF  # noqa: E731
    directories = DirectoryService(conn, admin, clock=clock)
    employees = EmployeeService(conn, admin, clock=clock)

    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    ids = _create_chain_via_dialog(qtbot, dlg, directories, monkeypatch)
    dlg.close()

    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Тестов Тест Тестович",
            position_id=ids["position_id"],
            branch_id=ids["branch_id"],
            department_id=ids["department_id"],
            division_id=ids["division_id"],
            employment_type_id=1,
        )
    )

    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    tabs = dlg.findChild(QTabWidget, "directoriesTabs")
    assert tabs is not None
    tabs.setCurrentIndex(_tab_index(dlg, "Должности"))
    archive_btn = dlg.findChild(QPushButton, "directoriesPositionArchiveBtn")
    _click(qtbot, archive_btn)
    dlg.close()

    new_card = EmployeeCardDialog(employees, directories, admin)
    qtbot.addWidget(new_card)
    assert not _combo_has_active_item(new_card._position, "Инженер")

    existing = EmployeeCardDialog(
        employees, directories, admin, employee_id=emp_id
    )
    qtbot.addWidget(existing)
    idx = existing._position.findData(ids["position_id"])
    assert idx >= 0
    assert existing._position.itemText(idx) == "Инженер"

    conn.close()
