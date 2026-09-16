"""UI acceptance: справочники оргструктуры (EPIC-004 UI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
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
from ui.directories_dialog import _NO_DEPARTMENT, DirectoriesDialog
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
        ]
    )
    monkeypatch.setattr(
        "ui.directories_dialog._prompt_text",
        lambda *_a, **_k: (next(prompts), True),
    )

    class _PositionDialogStub:
        def __init__(
            self,
            parent: object,
            *,
            title: str,
            name: str,
            department_required: bool,
            division_required: bool,
        ) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

        def values(self) -> tuple[str, bool, bool]:
            return ("Инженер", False, False)

    monkeypatch.setattr(
        "ui.directories_dialog._PositionRequirementsDialog",
        _PositionDialogStub,
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
    pos_parent = dlg.findChild(QComboBox, "directoriesPositionParent")
    assert pos_parent is not None
    _select_combo(pos_parent, branch_id)
    pos_btn = dlg.findChild(QPushButton, "directoriesPositionCreateBtn")
    _click(qtbot, pos_btn)
    pos_id = directories.list_positions(branch_id=branch_id, active_only=True)[0].id

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


@pytest.mark.acceptance
def test_directories_dialog_creates_branch_direct_division(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0008: отдел филиала без департамента через «— без департамента —»."""
    conn, admin, _db = _open_empty_db(tmp_path)
    clock = lambda: _AS_OF  # noqa: E731
    directories = DirectoryService(conn, admin, clock=clock)

    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)

    branch_btn = dlg.findChild(QPushButton, "directoriesBranchCreateBtn")
    monkeypatch.setattr(
        "ui.directories_dialog._prompt_text",
        lambda *_a, **_k: ("Филиал Центр", True),
    )
    _click(qtbot, branch_btn)
    branch_id = directories.list_branches(active_only=True)[0].id

    tabs = dlg.findChild(QTabWidget, "directoriesTabs")
    assert tabs is not None
    tabs.setCurrentIndex(_tab_index(dlg, "Отделы"))
    div_branch = dlg.findChild(QComboBox, "directoriesDivisionExtraParent")
    div_dept = dlg.findChild(QComboBox, "directoriesDivisionParent")
    assert div_branch is not None and div_dept is not None
    _select_combo(div_branch, branch_id)
    _select_combo(div_dept, _NO_DEPARTMENT)
    monkeypatch.setattr(
        "ui.directories_dialog._prompt_text",
        lambda *_a, **_k: ("Секретариат филиала", True),
    )
    div_btn = dlg.findChild(QPushButton, "directoriesDivisionCreateBtn")
    _click(qtbot, div_btn)

    row = conn.execute(
        "SELECT branch_id, department_id FROM divisions WHERE name = ?",
        ("Секретариат филиала",),
    ).fetchone()
    assert row == (branch_id, None)
    dlg.close()
    conn.close()


def _open_directories(tmp_path: Path) -> tuple[object, SessionState, DirectoryService, Path]:
    conn, admin, db = _open_empty_db(tmp_path)
    clock = lambda: _AS_OF  # noqa: E731
    directories = DirectoryService(conn, admin, clock=clock)
    return conn, admin, directories, db


def _position_panel(dlg: DirectoriesDialog) -> None:
    tabs = dlg.findChild(QTabWidget, "directoriesTabs")
    assert tabs is not None
    tabs.setCurrentIndex(_tab_index(dlg, "Должности"))


def _select_position_branch(dlg: DirectoriesDialog, branch_id: int) -> None:
    pos_parent = dlg.findChild(QComboBox, "directoriesPositionParent")
    assert pos_parent is not None
    _select_combo(pos_parent, branch_id)


@pytest.mark.acceptance
def test_directories_create_position_persists_requirement_checkboxes(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, admin, directories, _db = _open_directories(tmp_path)
    branch_id = directories.create_branch("Филиал Центр")
    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)

    class _Dialog:
        def __init__(self, *_a, **_k) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

        def values(self) -> tuple[str, bool, bool]:
            return ("Бухгалтер", True, True)

    monkeypatch.setattr("ui.directories_dialog._PositionRequirementsDialog", _Dialog)
    _position_panel(dlg)
    _select_position_branch(dlg, branch_id)
    _click(qtbot, dlg.findChild(QPushButton, "directoriesPositionCreateBtn"))

    pos = next(
        p
        for p in directories.list_positions(branch_id=branch_id, active_only=True)
        if p.name == "Бухгалтер"
    )
    assert pos.department_required is True
    assert pos.division_required is True
    dlg.close()
    conn.close()


@pytest.mark.acceptance
def test_directories_position_tab_requires_branch_selection(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, admin, directories, _db = _open_directories(tmp_path)
    directories.create_branch("Филиал Центр")
    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    infos: list[tuple[object, ...]] = []

    def _information(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        infos.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", _information)
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)

    class _Dialog:
        def __init__(self, *_a, **_k) -> None:
            raise AssertionError("requirements dialog must not open without branch")

    monkeypatch.setattr("ui.directories_dialog._PositionRequirementsDialog", _Dialog)
    _position_panel(dlg)
    _click(qtbot, dlg.findChild(QPushButton, "directoriesPositionCreateBtn"))

    assert infos
    assert "Выберите филиал" in str(infos[0])
    assert directories.list_positions(active_only=False) == []
    dlg.close()
    conn.close()


@pytest.mark.acceptance
def test_directories_position_list_filtered_by_branch(
    qtbot, tmp_path: Path
) -> None:
    conn, admin, directories, _db = _open_directories(tmp_path)
    branch_a = directories.create_branch("Филиал A")
    branch_b = directories.create_branch("Филиал B")
    directories.create_position(branch_a, "Инженер A")
    directories.create_position(branch_b, "Инженер B")
    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    _position_panel(dlg)
    table = dlg.findChild(QTableWidget, "directoriesPositionTable")
    assert table is not None

    def _names() -> list[str]:
        return [
            table.item(i, 0).text()
            for i in range(table.rowCount())
            if table.item(i, 0) is not None
        ]

    _select_position_branch(dlg, branch_a)
    assert _names() == ["Инженер A"]
    _select_position_branch(dlg, branch_b)
    assert _names() == ["Инженер B"]
    dlg.close()
    conn.close()


@pytest.mark.acceptance
def test_directories_rename_position_requirements_without_violators_applies_silently(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, admin, directories, _db = _open_directories(tmp_path)
    branch_id = directories.create_branch("Филиал Центр")
    pos_id = directories.create_position(branch_id, "Секретарь")
    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    _position_panel(dlg)
    _select_position_branch(dlg, branch_id)
    table = dlg.findChild(QTableWidget, "directoriesPositionTable")
    assert table is not None and table.rowCount() == 1
    questions: list[tuple[object, ...]] = []

    def _question(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        questions.append(args)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", _question)
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)

    class _Dialog:
        def __init__(self, *_a, **_k) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

        def values(self) -> tuple[str, bool, bool]:
            return ("Секретарь", True, False)

    monkeypatch.setattr("ui.directories_dialog._PositionRequirementsDialog", _Dialog)
    _click(qtbot, dlg.findChild(QPushButton, "directoriesPositionRenameBtn"))

    pos = directories.get_position(pos_id)
    assert pos is not None
    assert pos.department_required is True
    assert pos.division_required is False
    assert not questions
    dlg.close()
    conn.close()


@pytest.mark.acceptance
def test_directories_rename_position_requirements_with_violators_confirms(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, admin, directories, db = _open_directories(tmp_path)
    clock = lambda: _AS_OF  # noqa: E731
    employees = EmployeeService(conn, admin, clock=clock)
    branch_id = directories.create_branch("Филиал")
    pos_id = directories.create_position(branch_id, "Бухгалтер")
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Иванов Иван",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=None,
            division_id=None,
            employment_type_id=1,
        )
    )
    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    _position_panel(dlg)
    _select_position_branch(dlg, branch_id)
    table = dlg.findChild(QTableWidget, "directoriesPositionTable")
    assert table is not None
    table.selectRow(0)

    answers: list[QMessageBox.StandardButton] = []

    def _question(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "question", _question)
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)

    class _Dialog:
        def __init__(self, *_a, **_k) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

        def values(self) -> tuple[str, bool, bool]:
            return ("Бухгалтер", True, False)

    monkeypatch.setattr("ui.directories_dialog._PositionRequirementsDialog", _Dialog)

    answers.append(QMessageBox.StandardButton.No)
    _click(qtbot, dlg.findChild(QPushButton, "directoriesPositionRenameBtn"))
    pos = directories.get_position(pos_id)
    assert pos is not None and not pos.department_required

    answers.append(QMessageBox.StandardButton.Yes)
    _click(qtbot, dlg.findChild(QPushButton, "directoriesPositionRenameBtn"))
    pos = directories.get_position(pos_id)
    assert pos is not None and pos.department_required
    row = conn.execute(
        "SELECT department_id, needs_org_review FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert row == (None, 1)
    dlg.close()
    conn.close()


@pytest.mark.acceptance
def test_directories_rename_position_requirements_decline_leaves_data_unchanged(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, admin, directories, _db = _open_directories(tmp_path)
    clock = lambda: _AS_OF  # noqa: E731
    employees = EmployeeService(conn, admin, clock=clock)
    branch_id = directories.create_branch("Склад")
    pos_id = directories.create_position(branch_id, "Кладовщик")
    dept_id = directories.create_department(branch_id, "Логистика")
    emp_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Петров Петр",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=dept_id,
            division_id=None,
            employment_type_id=1,
        )
    )
    dlg = DirectoriesDialog(directories, admin)
    qtbot.addWidget(dlg)
    _position_panel(dlg)
    _select_position_branch(dlg, branch_id)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_a, **_k: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(QMessageBox, "warning", _fail_on_warning)

    class _Dialog:
        def __init__(self, *_a, **_k) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

        def values(self) -> tuple[str, bool, bool]:
            return ("Кладовщик", True, True)

    monkeypatch.setattr("ui.directories_dialog._PositionRequirementsDialog", _Dialog)
    _click(qtbot, dlg.findChild(QPushButton, "directoriesPositionRenameBtn"))

    pos = directories.get_position(pos_id)
    assert pos is not None and not pos.division_required
    row = conn.execute(
        "SELECT department_id, needs_org_review FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    assert row == (dept_id, 0)
    dlg.close()
    conn.close()
