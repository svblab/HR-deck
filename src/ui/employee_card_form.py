"""Форма карточки сотрудника: создание и просмотр/правка (ТЗ §3.1, EPIC-005 UI)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from domain.employee import (
    EmployeeCreateInput,
    EmployeeUpdateInput,
    EmployeeValidationError,
    SensitiveEmployeeInput,
    format_search_hit_label,
)
from domain.permissions import Permission
from services.authorization import AuthorizationError, AuthorizationService
from services.directories import DirectoryService
from services.employees import EmployeeError, EmployeeService
from services.session import SessionState
from ui.theme import TEXT_MUTED

_REQUIRED = (
    ("full_name", "ФИО"),
    ("position_id", "должность"),
    ("branch_id", "филиал"),
    ("department_id", "департамент"),
    ("division_id", "отдел"),
    ("employment_type_id", "тип занятости"),
)


class EmployeeCardDialog(QDialog):
    def __init__(
        self,
        employees: EmployeeService,
        directories: DirectoryService,
        session: SessionState,
        *,
        employee_id: int | None = None,
        parent: QWidget | None = None,
        authz: AuthorizationService | None = None,
    ) -> None:
        super().__init__(parent)
        self._employees = employees
        self._directories = directories
        self._session = session
        self._authz = authz or AuthorizationService()
        self._employee_id = employee_id
        self.saved_employee_id: int | None = None
        self._is_archived = False
        self._loading = False
        self._original_sensitive: tuple[str | None, str | None] = (None, None)
        self._sensitive_masked = False

        self._can_view_sensitive = self._authz.check(
            session.role, Permission.VIEW_SENSITIVE_EMPLOYEE_FIELDS
        )
        self._can_edit_sensitive = self._authz.check(
            session.role, Permission.EDIT_SENSITIVE_EMPLOYEE_FIELDS
        )
        can_manage = self._authz.check(session.role, Permission.MANAGE_EMPLOYEES)

        self.setObjectName("employeeCardDialog")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowTitle("Новый сотрудник" if employee_id is None else "Карточка сотрудника")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._name = QLineEdit(objectName="fieldFullName")
        self._name.editingFinished.connect(self._refresh_similar)
        self._position = QComboBox(objectName="fieldPosition")
        self._branch = QComboBox(objectName="fieldBranch")
        self._department = QComboBox(objectName="fieldDepartment")
        self._division = QComboBox(objectName="fieldDivision")
        self._employment = QComboBox(objectName="fieldEmploymentType")
        self._note = QLineEdit(objectName="fieldNote")
        form.addRow("ФИО", self._name)
        form.addRow("Должность", self._position)
        form.addRow("Филиал", self._branch)
        form.addRow("Департамент", self._department)
        form.addRow("Отдел", self._division)
        form.addRow("Тип занятости", self._employment)
        form.addRow("Примечание", self._note)
        self._home = QLineEdit(objectName="fieldHomeAddress")
        self._insurance = QLineEdit(objectName="fieldInsurance")
        if self._can_view_sensitive:
            form.addRow("Домашний адрес", self._home)
            form.addRow("Номер страхования", self._insurance)
            self._home.setEnabled(self._can_edit_sensitive)
            self._insurance.setEnabled(self._can_edit_sensitive)
        else:
            self._home.hide()
            self._insurance.hide()
        layout.addLayout(form)
        self._similar = QLabel(objectName="similarNamesHint")
        self._similar.setWordWrap(True)
        self._similar.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._similar.hide()
        layout.addWidget(self._similar)
        self._archived_label = QLabel("Сотрудник в архиве")
        self._archived_label.setObjectName("archivedEmployeeLabel")
        self._archived_label.setStyleSheet(f"color: {TEXT_MUTED}; font-weight: 600;")
        self._archived_label.hide()
        layout.addWidget(self._archived_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        if can_manage:
            save = buttons.addButton("Сохранить", QDialogButtonBox.ButtonRole.AcceptRole)
            save.setObjectName("saveEmployeeBtn")
            buttons.accepted.connect(self._submit)
            self._archive_btn = QPushButton("В архив")
            self._archive_btn.setObjectName("archiveEmployeeBtn")
            self._archive_btn.clicked.connect(self._toggle_archive)
            layout.addWidget(self._archive_btn)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._branch.currentIndexChanged.connect(self._on_branch_changed)
        self._department.currentIndexChanged.connect(self._on_dept_changed)
        self._fill_static_combos()
        if employee_id is not None:
            self._load(employee_id)
        if not can_manage:
            for widget in (
                self._name,
                self._position,
                self._branch,
                self._department,
                self._division,
                self._employment,
                self._note,
            ):
                widget.setEnabled(False)
        elif employee_id is not None:
            self._apply_archived_state()

    def _apply_archived_state(self) -> None:
        archived = self._is_archived
        self._archived_label.setVisible(archived)
        for widget in (
            self._name,
            self._position,
            self._branch,
            self._department,
            self._division,
            self._employment,
            self._note,
        ):
            widget.setEnabled(not archived)
        if self._can_edit_sensitive:
            self._home.setEnabled(not archived)
            self._insurance.setEnabled(not archived)
        save = self.findChild(QPushButton, "saveEmployeeBtn")
        if save is not None:
            save.setEnabled(not archived)
        if hasattr(self, "_archive_btn"):
            self._archive_btn.setText("Восстановить" if archived else "В архив")
            self._archive_btn.setEnabled(True)

    def _fill_static_combos(self) -> None:
        self._loading = True
        _fill_combo(self._position, self._directories.list_positions(active_only=True), "Должность")
        _fill_combo(self._branch, self._directories.list_branches(active_only=True), "Филиал")
        _fill_combo(
            self._employment,
            self._directories.list_employment_types(active_only=True),
            "Тип занятости",
        )
        self._fill_departments()
        self._fill_divisions()
        self._loading = False

    def _on_branch_changed(self) -> None:
        if self._loading:
            return
        self._fill_departments()
        self._fill_divisions()

    def _on_dept_changed(self) -> None:
        if self._loading:
            return
        self._fill_divisions()

    def _fill_departments(self) -> None:
        branch_id = _combo_id(self._branch)
        items = (
            self._directories.list_departments(branch_id=branch_id, active_only=True)
            if branch_id is not None
            else []
        )
        _fill_combo(self._department, items, "Департамент")

    def _fill_divisions(self) -> None:
        dept_id = _combo_id(self._department)
        items = (
            self._directories.list_divisions(department_id=dept_id, active_only=True)
            if dept_id is not None
            else []
        )
        _fill_combo(self._division, items, "Отдел")

    def _load(self, employee_id: int) -> None:
        card = self._employees.get_employee(employee_id)
        self._is_archived = card.is_archived
        self._loading = True
        self._name.setText(card.full_name)
        _select(self._position, card.position_id)
        _select(self._branch, card.branch_id)
        self._fill_departments()
        _select(self._department, card.department_id)
        self._fill_divisions()
        if card.division_id is not None:
            _select(self._division, card.division_id)
        _select(self._employment, card.employment_type_id)
        self._note.setText(card.note or "")
        self._sensitive_masked = card.sensitive_fields_masked
        self._original_sensitive = (card.home_address, card.social_insurance_number)
        if self._can_view_sensitive:
            self._home.setText(card.home_address or "")
            self._insurance.setText(card.social_insurance_number or "")
        self._loading = False
        self._refresh_similar()
        self._apply_archived_state()

    def _toggle_archive(self) -> None:
        if self._employee_id is None:
            return
        if self._is_archived:
            text = "Восстановить сотрудника из архива?"
            title = "Восстановление"
        else:
            text = (
                "Перевести сотрудника в архив? Он будет скрыт из списков "
                "по умолчанию; история статусов сохранится."
            )
            title = "Архивирование"
        if (
            QMessageBox.question(self, title, text)
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            if self._is_archived:
                self._employees.restore_employee(self._employee_id)
            else:
                self._employees.archive_employee(self._employee_id)
        except (EmployeeError, AuthorizationError) as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return
        self.saved_employee_id = self._employee_id
        self.accept()

    def _refresh_similar(self) -> None:
        prefix = self._name.text().strip()
        if not prefix:
            self._similar.hide()
            return
        hits = [
            h
            for h in self._employees.search_by_name(prefix)
            if h.id != self._employee_id
        ]
        if not hits:
            self._similar.hide()
            return
        lines = "\n".join(format_search_hit_label(h) for h in hits[:8])
        self._similar.setText(f"Сотрудники с похожим ФИО:\n{lines}")
        self._similar.show()

    def _missing_required(self) -> list[str]:
        values = {
            "full_name": self._name.text().strip() or None,
            "position_id": _combo_id(self._position),
            "branch_id": _combo_id(self._branch),
            "department_id": _combo_id(self._department),
            "division_id": _combo_id(self._division),
            "employment_type_id": _combo_id(self._employment),
        }
        return [label for key, label in _REQUIRED if values[key] is None]

    def _payload(self) -> EmployeeCreateInput:
        return EmployeeCreateInput(
            full_name=self._name.text(),
            position_id=_combo_id(self._position) or 0,
            branch_id=_combo_id(self._branch) or 0,
            department_id=_combo_id(self._department) or 0,
            employment_type_id=_combo_id(self._employment) or 0,
            division_id=_combo_id(self._division),
            note=self._note.text().strip() or None,
        )

    def _submit(self) -> None:
        missing = self._missing_required()
        if missing:
            QMessageBox.warning(self, "Проверьте поля", f"Заполните: {', '.join(missing)}.")
            return
        payload = self._payload()
        try:
            if self._employee_id is None:
                new_id = self._employees.create_employee(payload)
                self._save_sensitive(new_id)
                self.saved_employee_id = new_id
            else:
                self._employees.update_employee(
                    self._employee_id,
                    EmployeeUpdateInput(
                        full_name=payload.full_name,
                        position_id=payload.position_id,
                        branch_id=payload.branch_id,
                        department_id=payload.department_id,
                        employment_type_id=payload.employment_type_id,
                        division_id=payload.division_id,
                        note=payload.note,
                    ),
                )
                self._save_sensitive(self._employee_id)
                self.saved_employee_id = self._employee_id
        except (EmployeeError, EmployeeValidationError, AuthorizationError) as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return
        self.accept()

    def _save_sensitive(self, employee_id: int) -> None:
        if not self._can_edit_sensitive or self._sensitive_masked:
            return
        home = self._home.text().strip() or None
        insurance = self._insurance.text().strip() or None
        if (home, insurance) == self._original_sensitive and self._employee_id is not None:
            return
        if home is None and insurance is None and self._employee_id is None:
            return
        self._employees.update_sensitive_fields(
            employee_id,
            SensitiveEmployeeInput(home_address=home, social_insurance_number=insurance),
        )


def _combo_id(combo: QComboBox) -> int | None:
    data = combo.currentData()
    return int(data) if data is not None else None


def _fill_combo(combo: QComboBox, items: list, placeholder: str) -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(placeholder, None)
    for item in items:
        combo.addItem(item.name, item.id)
    combo.blockSignals(False)


def _select(combo: QComboBox, value: int) -> None:
    idx = combo.findData(value)
    if idx >= 0:
        combo.setCurrentIndex(idx)
