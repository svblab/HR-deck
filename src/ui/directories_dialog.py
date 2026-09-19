"""Диалог управления справочниками оргструктуры (EPIC-004 UI)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from domain.permissions import Permission, has_permission
from services.authorization import AuthorizationError
from services.directories import DirectoryError, DirectoryService
from services.session import SessionState

_USER_ROLE = 256  # Qt.ItemDataRole.UserRole
_NO_DEPARTMENT = -1


class DirectoriesDialog(QDialog):
    def __init__(
        self,
        directories: DirectoryService,
        session: SessionState,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._directories = directories
        self._session = session
        self._can_manage = has_permission(session.role, Permission.MANAGE_DIRECTORIES)
        self.setObjectName("directoriesDialog")
        self.setWindowTitle("Справочники")
        self.setModal(True)
        self.setMinimumWidth(720)

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget(objectName="directoriesTabs")
        self._branch_panel = _DirectoryPanel(
            directories,
            self._can_manage,
            kind="branch",
            title="Филиалы",
            object_prefix="directoriesBranch",
            reload=self._reload_branch_dependents,
        )
        self._dept_panel = _DirectoryPanel(
            directories,
            self._can_manage,
            kind="department",
            title="Департаменты",
            object_prefix="directoriesDepartment",
            parent_label="Филиал",
        )
        self._div_panel = _DirectoryPanel(
            directories,
            self._can_manage,
            kind="division",
            title="Отделы",
            object_prefix="directoriesDivision",
            parent_label="Департамент",
            extra_parent_label="Филиал",
            extra_parent_changed=self._on_div_branch_changed,
            include_no_parent_option=True,
        )
        self._pos_panel = _DirectoryPanel(
            directories,
            self._can_manage,
            kind="position",
            title="Должности",
            object_prefix="directoriesPosition",
            parent_label="Филиал",
        )
        self._panels = [
            self._branch_panel,
            self._dept_panel,
            self._div_panel,
            self._pos_panel,
            _DirectoryPanel(
                directories,
                self._can_manage,
                kind="employment_type",
                title="Типы занятости",
                object_prefix="directoriesEmployment",
                extra_column="Код",
            ),
        ]
        self._dept_panel.set_parent_items(self._branch_panel.items_for_combo())
        self._pos_panel.set_parent_items(self._branch_panel.items_for_combo())
        self._div_panel.set_extra_parent_items(self._branch_panel.items_for_combo())
        for panel in self._panels:
            self._tabs.addTab(panel, panel.title)
        layout.addWidget(self._tabs, stretch=1)

        close_btn = QPushButton("Закрыть", objectName="directoriesCloseBtn")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)

        self._reload_branch_dependents()

    def _reload_branch_dependents(self) -> None:
        self._dept_panel.set_parent_items(self._branch_panel.items_for_combo())
        self._pos_panel.set_parent_items(self._branch_panel.items_for_combo())
        self._div_panel.set_extra_parent_items(self._branch_panel.items_for_combo())
        self._on_div_branch_changed()

    def _on_div_branch_changed(self) -> None:
        branch_id = self._div_panel.extra_parent_id()
        departments = (
            self._directories.list_departments(branch_id=branch_id, active_only=False)
            if branch_id is not None
            else []
        )
        self._div_panel.set_parent_items([(d.id, d.name) for d in departments])


class _DirectoryPanel(QWidget):
    def __init__(
        self,
        directories: DirectoryService,
        can_manage: bool,
        *,
        kind: str,
        title: str,
        object_prefix: str,
        parent_label: str | None = None,
        extra_parent_label: str | None = None,
        extra_column: str | None = None,
        list_items: Callable[[bool], list] | None = None,
        extra_parent_changed: Callable[[], None] | None = None,
        reload: Callable[[], None] | None = None,
        include_no_parent_option: bool = False,
    ) -> None:
        super().__init__()
        self._directories = directories
        self._can_manage = can_manage
        self._kind = kind
        self.title = title
        self._object_prefix = object_prefix
        self._list_items = list_items
        self._extra_parent_changed = extra_parent_changed
        self._reload_hook = reload
        self._include_no_parent_option = include_no_parent_option

        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self._active_only = QCheckBox("Только активные", objectName=f"{object_prefix}ActiveOnly")
        self._active_only.setChecked(True)
        self._active_only.toggled.connect(self.reload)
        filters.addWidget(self._active_only)
        filters.addStretch(1)
        layout.addLayout(filters)

        self._extra_parent: QComboBox | None = None
        if extra_parent_label is not None:
            row = QHBoxLayout()
            row.addWidget(QLabel(extra_parent_label))
            self._extra_parent = QComboBox(objectName=f"{object_prefix}ExtraParent")
            self._extra_parent.currentIndexChanged.connect(self._on_extra_parent_changed)
            row.addWidget(self._extra_parent, stretch=1)
            layout.addLayout(row)

        self._parent: QComboBox | None = None
        if parent_label is not None:
            row = QHBoxLayout()
            row.addWidget(QLabel(parent_label))
            self._parent = QComboBox(objectName=f"{object_prefix}Parent")
            self._parent.currentIndexChanged.connect(self.reload)
            row.addWidget(self._parent, stretch=1)
            layout.addLayout(row)

        columns = ["Название", "Архив"]
        if extra_column is not None:
            columns = [extra_column, *columns]
        self._table = QTableWidget(objectName=f"{object_prefix}Table")
        self._table.setColumnCount(len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, stretch=1)

        buttons = QHBoxLayout()
        self._create_btn = QPushButton("Создать…", objectName=f"{object_prefix}CreateBtn")
        self._rename_btn = QPushButton("Переименовать…", objectName=f"{object_prefix}RenameBtn")
        self._archive_btn = QPushButton("В архив", objectName=f"{object_prefix}ArchiveBtn")
        self._restore_btn = QPushButton("Восстановить", objectName=f"{object_prefix}RestoreBtn")
        refresh_btn = QPushButton("Обновить", objectName=f"{object_prefix}RefreshBtn")
        for btn in (
            self._create_btn,
            self._rename_btn,
            self._archive_btn,
            self._restore_btn,
        ):
            btn.setEnabled(can_manage)
        self._create_btn.clicked.connect(self._create)
        self._rename_btn.clicked.connect(self._rename)
        self._archive_btn.clicked.connect(self._archive)
        self._restore_btn.clicked.connect(self._restore)
        refresh_btn.clicked.connect(self.reload)
        for btn in (
            self._create_btn,
            self._rename_btn,
            self._archive_btn,
            self._restore_btn,
            refresh_btn,
        ):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._initializing = True
        self.reload()
        self._initializing = False

    def set_parent_items(self, items: list[tuple[int, str]]) -> None:
        if self._parent is None:
            return
        current = self._parent.currentData()
        self._parent.blockSignals(True)
        self._parent.clear()
        self._parent.addItem("— выберите —", None)
        if self._include_no_parent_option:
            self._parent.addItem("— без департамента (отдел филиала) —", _NO_DEPARTMENT)
        for item_id, name in items:
            self._parent.addItem(name, item_id)
        if current is not None:
            idx = self._parent.findData(current)
            if idx >= 0:
                self._parent.setCurrentIndex(idx)
        self._parent.blockSignals(False)
        self.reload()

    def set_extra_parent_items(self, items: list[tuple[int, str]]) -> None:
        if self._extra_parent is None:
            return
        current = self._extra_parent.currentData()
        self._extra_parent.blockSignals(True)
        self._extra_parent.clear()
        self._extra_parent.addItem("— выберите —", None)
        for item_id, name in items:
            self._extra_parent.addItem(name, item_id)
        if current is not None:
            idx = self._extra_parent.findData(current)
            if idx >= 0:
                self._extra_parent.setCurrentIndex(idx)
        self._extra_parent.blockSignals(False)
        if self._extra_parent_changed is not None:
            self._extra_parent_changed()

    def items_for_combo(self) -> list[tuple[int, str]]:
        rows = self._fetch_rows(active_only=False)
        return [(row.id, row.name) for row in rows if not row.is_archived]

    def extra_parent_id(self) -> int | None:
        if self._extra_parent is None:
            return None
        data = self._extra_parent.currentData()
        return int(data) if data is not None else None

    def _on_extra_parent_changed(self) -> None:
        if self._extra_parent_changed is not None:
            self._extra_parent_changed()

    def reload(self) -> None:
        active = self._active_only.isChecked()
        rows = self._fetch_rows(active_only=active)
        name_col = 1 if self._kind == "employment_type" else 0
        archive_col = name_col + 1
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            if self._kind == "employment_type":
                self._table.setItem(i, 0, QTableWidgetItem(row.code))
            name_item = QTableWidgetItem(row.name)
            name_item.setData(_USER_ROLE, row.id)
            self._table.setItem(i, name_col, name_item)
            self._table.setItem(
                i,
                archive_col,
                QTableWidgetItem("да" if row.is_archived else "нет"),
            )
        if rows:
            self._table.selectRow(0)
        if self._reload_hook is not None and not self._initializing:
            self._reload_hook()

    def _fetch_rows(self, *, active_only: bool):
        if self._list_items is not None:
            return self._list_items(active_only)
        if self._kind == "branch":
            return self._directories.list_branches(active_only=active_only)
        if self._kind == "department":
            branch_id = self._parent_id()
            if branch_id is None:
                return []
            return self._directories.list_departments(
                branch_id=branch_id,
                active_only=active_only,
            )
        if self._kind == "division":
            branch_id = self.extra_parent_id()
            if branch_id is None:
                return []
            return self._directories.list_divisions(
                branch_id=branch_id,
                department_id=self._parent_id() if self._parent_id() != _NO_DEPARTMENT else None,
                active_only=active_only,
            )
        if self._kind == "position":
            branch_id = self._parent_id()
            if branch_id is None:
                return []
            return self._directories.list_positions(
                branch_id=branch_id,
                active_only=active_only,
            )
        if self._kind == "employment_type":
            return self._directories.list_employment_types(active_only=active_only)
        return []

    def _selected_id(self) -> int | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        name_col = 1 if self._kind == "employment_type" else 0
        item = self._table.item(row, name_col)
        if item is None:
            return None
        data = item.data(_USER_ROLE)
        return int(data) if data is not None else None

    def _parent_id(self) -> int | None:
        if self._parent is None:
            return None
        data = self._parent.currentData()
        return int(data) if data is not None else None

    def _warn(self, title: str, exc: Exception) -> None:
        QMessageBox.warning(self, title, str(exc))

    def _create(self) -> None:
        if self._kind == "department":
            parent_id = self._parent_id()
            if parent_id is None:
                QMessageBox.information(self, "Создание", "Выберите филиал.")
                return
        elif self._kind == "division":
            branch_id = self.extra_parent_id()
            if branch_id is None:
                QMessageBox.information(self, "Создание", "Выберите филиал.")
                return
            parent_id = self._parent_id()
            if parent_id is None:
                QMessageBox.information(
                    self,
                    "Создание",
                    "Выберите департамент или «— без департамента —».",
                )
                return
        elif self._kind == "employment_type":
            code, ok = _prompt_text(self, "Код типа занятости", "")
            if not ok or not code.strip():
                return
            name, ok = _prompt_text(self, "Название типа занятости", code.strip())
            if not ok or not name.strip():
                return
            try:
                self._directories.create_employment_type(code.strip(), name.strip())
            except (DirectoryError, AuthorizationError) as exc:
                self._warn("Создание", exc)
                return
            self.reload()
            return
        elif self._kind == "position":
            parent_id = self._parent_id()
            if parent_id is None:
                QMessageBox.information(self, "Создание", "Выберите филиал.")
                return
            dialog = _PositionRequirementsDialog(
                self,
                title="Новая должность",
                name="",
                department_required=False,
                division_required=False,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            name, dept_required, div_required = dialog.values()
            if not name:
                return
            try:
                self._directories.create_position(
                    parent_id,
                    name,
                    department_required=dept_required,
                    division_required=div_required,
                )
            except (DirectoryError, AuthorizationError) as exc:
                self._warn("Создание", exc)
                return
            self.reload()
            return
        else:
            parent_id = None

        name, ok = _prompt_text(self, "Название", "")
        if not ok or not name.strip():
            return
        try:
            if self._kind == "branch":
                self._directories.create_branch(name.strip())
            elif self._kind == "department":
                assert parent_id is not None
                self._directories.create_department(parent_id, name.strip())
            elif self._kind == "division":
                assert parent_id is not None
                branch_id = self.extra_parent_id()
                assert branch_id is not None
                dept_id = None if parent_id == _NO_DEPARTMENT else parent_id
                self._directories.create_division(branch_id, dept_id, name.strip())
        except (DirectoryError, AuthorizationError) as exc:
            self._warn("Создание", exc)
            return
        self.reload()

    def _rename(self) -> None:
        entity_id = self._selected_id()
        if entity_id is None:
            return
        if self._kind == "position":
            current = self._directories.get_position(entity_id)
            if current is None:
                return
            dialog = _PositionRequirementsDialog(
                self,
                title="Изменение должности",
                name=current.name,
                department_required=current.department_required,
                division_required=current.division_required,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            new_name, new_dept_required, new_div_required = dialog.values()
            if not new_name:
                return
            try:
                if new_name != current.name:
                    self._directories.rename_position(entity_id, new_name)
                if (new_dept_required, new_div_required) != (
                    current.department_required,
                    current.division_required,
                ):
                    violators = self._directories.preview_position_requirement_change(
                        entity_id,
                        department_required=new_dept_required,
                        division_required=new_div_required,
                    )
                    if violators:
                        names = "\n".join(f"— {e.full_name}" for e in violators[:20])
                        more = (
                            f"\n… и ещё {len(violators) - 20}"
                            if len(violators) > 20
                            else ""
                        )
                        proceed = QMessageBox.question(
                            self,
                            "Требования должности",
                            f"{len(violators)} сотрудник(ов) перестанут соответствовать "
                            f"новым требованиям и будут помечены «Требует внимания» "
                            f"(департамент и/или отдел будут сброшены):\n{names}{more}\n\n"
                            "Продолжить?",
                        )
                        if proceed != QMessageBox.StandardButton.Yes:
                            self.reload()
                            return
                    self._directories.apply_position_requirement_change(
                        entity_id,
                        department_required=new_dept_required,
                        division_required=new_div_required,
                        reset_violations=bool(violators),
                    )
            except (DirectoryError, AuthorizationError) as exc:
                self._warn("Изменение должности", exc)
                return
            self.reload()
            return
        row = self._table.currentRow()
        name_col = 1 if self._kind == "employment_type" else 0
        current = self._table.item(row, name_col)
        default = current.text() if current is not None else ""
        name, ok = _prompt_text(self, "Новое название", default)
        if not ok or not name.strip():
            return
        try:
            if self._kind == "branch":
                self._directories.rename_branch(entity_id, name.strip())
            elif self._kind == "department":
                self._directories.rename_department(entity_id, name.strip())
            elif self._kind == "division":
                self._directories.rename_division(entity_id, name.strip())
            elif self._kind == "employment_type":
                self._directories.rename_employment_type(entity_id, name.strip())
        except (DirectoryError, AuthorizationError) as exc:
            self._warn("Переименование", exc)
            return
        self.reload()

    def _archive(self) -> None:
        entity_id = self._selected_id()
        if entity_id is None:
            return
        try:
            if self._kind == "branch":
                self._directories.archive_branch(entity_id)
            elif self._kind == "department":
                self._directories.archive_department(entity_id)
            elif self._kind == "division":
                self._directories.archive_division(entity_id)
            elif self._kind == "position":
                self._directories.archive_position(entity_id)
            elif self._kind == "employment_type":
                self._directories.archive_employment_type(entity_id)
        except (DirectoryError, AuthorizationError) as exc:
            self._warn("Архив", exc)
            return
        self.reload()

    def _restore(self) -> None:
        entity_id = self._selected_id()
        if entity_id is None:
            return
        try:
            if self._kind == "branch":
                self._directories.unarchive_branch(entity_id)
            elif self._kind == "department":
                self._directories.unarchive_department(entity_id)
            elif self._kind == "division":
                self._directories.unarchive_division(entity_id)
            elif self._kind == "position":
                self._directories.unarchive_position(entity_id)
            elif self._kind == "employment_type":
                self._directories.unarchive_employment_type(entity_id)
        except (DirectoryError, AuthorizationError) as exc:
            self._warn("Восстановление", exc)
            return
        self.reload()


def _prompt_text(parent: QWidget, title: str, default: str) -> tuple[str, bool]:
    from PySide6.QtWidgets import QInputDialog

    text, ok = QInputDialog.getText(parent, title, "Название:", text=default)
    return text, ok


class _PositionRequirementsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        title: str,
        name: str,
        department_required: bool,
        division_required: bool,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Название:"))
        self._name = QLineEdit(name)
        layout.addWidget(self._name)
        self._dept_required = QCheckBox("Департамент обязателен")
        self._dept_required.setChecked(department_required)
        layout.addWidget(self._dept_required)
        self._div_required = QCheckBox("Отдел обязателен")
        self._div_required.setChecked(division_required)
        layout.addWidget(self._div_required)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, bool, bool]:
        return (
            self._name.text().strip(),
            self._dept_required.isChecked(),
            self._div_required.isChecked(),
        )
