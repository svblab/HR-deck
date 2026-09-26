"""EPIC-018: построчный визард конвертации сотрудников (ADR-0012)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from data.db import Connection
from data.import_sessions import ImportSessionRepository
from domain.employee import (
    EmployeeCreateInput,
    EmployeeValidationError,
    format_search_hit_label,
    normalize_name_for_match,
)
from services.directories import DirectoryService
from services.employee_conversion import EmployeeConversionError, EmployeeConversionService
from services.employees import EmployeeError, EmployeeService
from services.import_conversion_ingest import (
    ImportConversionIngestError,
    ImportConversionIngestService,
)
from services.session import SessionState
from services.status_history import StatusHistoryService
from ui.employee_card_form import EmployeeCardDialog

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_conversion_wizard_flow(
    parent: QWidget,
    conn: Connection,
    session: SessionState,
    employees: EmployeeService,
    directories: DirectoryService,
    *,
    status_history: StatusHistoryService | None = None,
    clock: Clock | None = None,
) -> bool:
    """Temporary EPIC-018 entry point until EPIC-021 shell."""
    path, _filter = QFileDialog.getOpenFileName(
        parent,
        "Конвертация данных",
        "",
        "Таблицы (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv)",
    )
    if not path:
        return False
    tick: Clock = clock or _utc_now
    ingest = ImportConversionIngestService(conn, session, clock=tick)
    sessions = ImportSessionRepository(conn)
    try:
        result = ingest.ingest_file(path)
    except ImportConversionIngestError as exc:
        QMessageBox.warning(parent, "Конвертация", str(exc))
        return False
    if result.resumed:
        sessions.touch_session(result.session_id, last_accessed_at=tick())
        conn.commit()
    conversion = EmployeeConversionService(conn, session, employees, sessions=sessions)
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=result.session_id,
        clock=tick,
        status_history=status_history,
        parent=parent,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


class ConversionWizardDialog(QDialog):
    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        employees: EmployeeService,
        directories: DirectoryService,
        *,
        conversion: EmployeeConversionService,
        sessions: ImportSessionRepository,
        session_id: int,
        clock: Clock,
        status_history: StatusHistoryService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._session = session
        self._employees = employees
        self._directories = directories
        self._conversion = conversion
        self._sessions = sessions
        self._session_id = session_id
        self._clock = clock
        self._row_id: int | None = None
        self._duplicate_match_ids: list[int] = []

        self.setObjectName("conversionWizardDialog")
        self.setWindowTitle("Конвертация данных")
        self.setModal(True)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        self._progress = QLabel(objectName="conversionWizardProgress")
        root.addWidget(self._progress)

        self._duplicate_banner = QLabel(objectName="conversionDuplicateBanner")
        self._duplicate_banner.setWordWrap(True)
        self._duplicate_banner.hide()
        root.addWidget(self._duplicate_banner)

        dup_row = QHBoxLayout()
        self._view_duplicate_btn = QPushButton(
            "Просмотр совпадения", objectName="conversionViewDuplicateBtn"
        )
        self._view_duplicate_btn.clicked.connect(self._open_duplicate_reference)
        self._view_duplicate_btn.hide()
        dup_row.addWidget(self._view_duplicate_btn)
        dup_row.addStretch(1)
        root.addLayout(dup_row)

        self._card = EmployeeCardDialog(
            employees,
            directories,
            session,
            status_history=status_history,
            parent=self,
        )
        self._card.setWindowFlags(Qt.WindowType.Widget)
        inner_save = self._card.findChild(QPushButton, "saveEmployeeBtn")
        if inner_save is not None:
            inner_save.hide()
        archive = self._card.findChild(QPushButton, "archiveEmployeeBtn")
        if archive is not None:
            archive.hide()
        assign = self._card.findChild(QPushButton, "assignStatusFromCardBtn")
        if assign is not None:
            assign.hide()
        root.addWidget(self._card)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._save_btn = buttons.addButton(
            "Сохранить", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._save_btn.setObjectName("conversionWizardSaveBtn")
        self._skip_btn = buttons.addButton("Пропустить", QDialogButtonBox.ButtonRole.ActionRole)
        self._skip_btn.setObjectName("conversionWizardSkipBtn")
        buttons.rejected.connect(self.reject)
        self._save_btn.clicked.connect(self._on_save)
        self._skip_btn.clicked.connect(self._on_skip)
        root.addWidget(buttons)

        self._load_current_row()

    def _load_current_row(self) -> None:
        rows = self._sessions.list_rows(self._session_id)
        if not rows:
            self.accept()
            return
        row = rows[0]
        self._row_id = row.id
        values = json.loads(row.values_json)
        self._prefill_card(values)
        self._update_duplicate_warning(values.get("full_name", ""))
        self._progress.setText(
            f"Исходная строка {row.source_row_number} · осталось {len(rows)}"
        )

    def _prefill_card(self, values: dict[str, str]) -> None:
        name = self._card.findChild(QLineEdit, "fieldFullName")
        if name is not None:
            name.setText(values.get("full_name", ""))
        self._select_combo_by_text("fieldBranch", values.get("branch", ""))
        self._select_combo_by_text("fieldDepartment", values.get("department", ""))
        self._select_combo_by_text("fieldDivision", values.get("division", ""))
        self._select_combo_by_text("fieldPosition", values.get("position", ""))
        self._select_combo_by_text("fieldEmploymentType", values.get("employment_type", ""))
        note = self._card.findChild(QLineEdit, "fieldNote")
        if note is not None:
            note.clear()

    def _select_combo_by_text(self, object_name: str, raw: str) -> None:
        combo = self._card.findChild(QComboBox, object_name)
        if combo is None:
            return
        key = raw.strip().casefold()
        if not key:
            combo.setCurrentIndex(0)
            return
        for idx in range(combo.count()):
            if combo.itemText(idx).strip().casefold() == key:
                combo.setCurrentIndex(idx)
                return
        combo.setCurrentIndex(0)

    def _build_input_from_card(self) -> tuple[EmployeeCreateInput | None, list[str]]:
        name = self._card.findChild(QLineEdit, "fieldFullName")
        position = self._card.findChild(QComboBox, "fieldPosition")
        branch = self._card.findChild(QComboBox, "fieldBranch")
        department = self._card.findChild(QComboBox, "fieldDepartment")
        division = self._card.findChild(QComboBox, "fieldDivision")
        employment = self._card.findChild(QComboBox, "fieldEmploymentType")
        note = self._card.findChild(QLineEdit, "fieldNote")
        if not all((name, position, branch, department, division, employment, note)):
            return None, ["форма"]
        assert name is not None
        assert position is not None
        assert branch is not None
        assert department is not None
        assert division is not None
        assert employment is not None
        assert note is not None
        missing: list[str] = []
        if not name.text().strip():
            missing.append("ФИО")
        if _combo_id(position) is None:
            missing.append("должность")
        if _combo_id(branch) is None:
            missing.append("филиал")
        if _combo_id(employment) is None:
            missing.append("тип занятости")
        if missing:
            return None, missing
        payload = EmployeeCreateInput(
            full_name=name.text(),
            position_id=_combo_id(position) or 0,
            branch_id=_combo_id(branch) or 0,
            department_id=_combo_id(department),
            employment_type_id=_combo_id(employment) or 0,
            division_id=_combo_id(division),
            note=note.text().strip() or None,
        )
        try:
            validated = self._employees.validate_card_input(payload)
        except (EmployeeError, EmployeeValidationError) as exc:
            return None, [str(exc)]
        return validated, []

    def _update_duplicate_warning(self, full_name: str) -> None:
        clean = full_name.strip()
        if not clean:
            self._duplicate_banner.hide()
            self._view_duplicate_btn.hide()
            self._duplicate_match_ids = []
            return
        needle = normalize_name_for_match(clean)
        hits = [
            hit
            for hit in self._employees.search_by_name(clean)
            if normalize_name_for_match(hit.full_name) == needle
        ]
        self._duplicate_match_ids = [hit.id for hit in hits]
        if not hits:
            self._duplicate_banner.hide()
            self._view_duplicate_btn.hide()
            return
        labels = "; ".join(format_search_hit_label(hit) for hit in hits[:5])
        self._duplicate_banner.setText(
            "Возможный дубль по ФИО (существующая карточка не будет изменена "
            f"автоматически): {labels}"
        )
        self._duplicate_banner.show()
        self._view_duplicate_btn.setVisible(len(hits) == 1)

    def _open_duplicate_reference(self) -> None:
        if len(self._duplicate_match_ids) != 1:
            return
        employee_id = self._duplicate_match_ids[0]
        dialog = EmployeeCardDialog(
            self._employees,
            self._directories,
            self._session,
            employee_id=employee_id,
            parent=self,
        )
        for widget in dialog.findChildren(QLineEdit):
            widget.setEnabled(False)
        for combo_widget in dialog.findChildren(QComboBox):
            combo_widget.setEnabled(False)
        archive = dialog.findChild(QPushButton, "archiveEmployeeBtn")
        if archive is not None:
            archive.hide()
        save = dialog.findChild(QPushButton, "saveEmployeeBtn")
        if save is not None:
            save.hide()
        dialog.exec()

    def _on_save(self) -> None:
        if self._row_id is None:
            return
        payload, missing = self._build_input_from_card()
        if payload is None:
            QMessageBox.warning(
                self, "Проверьте поля", f"Заполните: {', '.join(missing)}."
            )
            return
        now = self._clock()
        try:
            self._conversion.save_row(
                session_id=self._session_id,
                row_id=self._row_id,
                data=payload,
                last_accessed_at=now,
            )
        except (EmployeeConversionError, EmployeeError, EmployeeValidationError) as exc:
            QMessageBox.warning(self, "Сохранение", str(exc))
            return
        self._load_current_row()

    def _on_skip(self) -> None:
        if self._row_id is None:
            return
        now = self._clock()
        try:
            self._conversion.skip_row(
                session_id=self._session_id,
                row_id=self._row_id,
                last_accessed_at=now,
            )
        except EmployeeConversionError as exc:
            QMessageBox.warning(self, "Пропуск", str(exc))
            return
        self._load_current_row()


def _combo_id(combo: QComboBox) -> int | None:
    data = combo.currentData()
    return int(data) if data is not None else None


__all__ = ["ConversionWizardDialog", "run_conversion_wizard_flow"]
