"""ADR-0013: UI for transport-package import confirmation gate (EPIC-021)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from data.db import Connection
from domain.employee_reconciliation import (
    EmployeeMatchResolution,
    EmployeeMatchResolutionChoice,
    EmployeeMatchStatus,
)
from domain.import_errors import ImportReason, format_import_reason
from services.employees import EmployeeService
from services.session import SessionState
from services.transport_import_apply import TransportImportApplyAdminService
from services.transport_import_validation import (
    ValidationDisposition,
    ValidationResult,
)
from services.transport_keys import TransportKeyStore
from services.transport_receive import (
    DecryptedTransportPackage,
    TransportReceiveAdminService,
)

OnDataChanged = Callable[[], None]

_PAGE_PICK = 0
_PAGE_SUMMARY = 1
_PAGE_CONFIRM = 2
_PAGE_RESULT = 3

# Confirmation copy must not imply a permanent external_id rebind (ADR-0013).
_ATTACH_LABEL = "Тот же человек (только для этого импорта)"
_CREATE_LABEL = "Это новый человек"
_ATTACH_NOTE = (
    "Выбор действует только для текущего импорта и не запоминается: "
    "при следующем пакете от того же отправителя вопрос может появиться снова."
)
_PRE_APPLY_BACKUP_NOTE = (
    "Перед применением будет создана автоматическая копия текущего состояния базы."
)


def _format_reasons(reasons: tuple[ImportReason, ...]) -> str:
    if not reasons:
        return "—"
    return "\n".join(format_import_reason(reason) for reason in reasons)


def _directory_counts(validation: ValidationResult) -> tuple[int, int]:
    plan = validation.directory_plan
    if plan is None:
        return 0, 0
    creates = (
        len(plan.branch_creates)
        + len(plan.department_creates)
        + len(plan.division_creates)
        + len(plan.position_creates)
    )
    updates = (
        len(plan.branch_updates)
        + len(plan.department_updates)
        + len(plan.division_updates)
        + len(plan.position_updates)
    )
    return creates, updates


def _employee_counts(validation: ValidationResult) -> tuple[int, int, int]:
    plan = validation.employee_plan
    if plan is None:
        return 0, 0, 0
    creates = sum(1 for i in plan.items if i.match.status is EmployeeMatchStatus.NEW)
    updates = sum(1 for i in plan.items if i.match.status is EmployeeMatchStatus.EXACT)
    return creates, updates, len(plan.confirmable)


def _plan_details_text(validation: ValidationResult) -> str:
    lines: list[str] = []
    dplan = validation.directory_plan
    if dplan is not None:
        lines.append("=== Справочники ===")
        for label, rows in (
            ("branch create", dplan.branch_creates),
            ("branch update", dplan.branch_updates),
            ("department create", dplan.department_creates),
            ("department update", dplan.department_updates),
            ("division create", dplan.division_creates),
            ("division update", dplan.division_updates),
            ("position create", dplan.position_creates),
            ("position update", dplan.position_updates),
        ):
            for row in rows:
                lines.append(f"  {label}: {row!r}")
        if dplan.broken_employees:
            lines.append("broken employees:")
            for emp_id, name in dplan.broken_employees:
                lines.append(f"  {emp_id} {name}")
    eplan = validation.employee_plan
    if eplan is not None:
        lines.append("=== Сотрудники (авто) ===")
        for item in eplan.items:
            ext = str(item.package_row.get("external_id"))
            name = str(item.package_row.get("full_name"))
            lines.append(f"  {item.match.status.value}: {ext} / {name}")
        if eplan.confirmable:
            lines.append("=== Требуют подтверждения ===")
            for item in eplan.confirmable:
                ext = str(item.package_row.get("external_id"))
                name = str(item.package_row.get("full_name"))
                lines.append(f"  {item.match.status.value}: {ext} / {name}")
        if eplan.conflicts:
            lines.append("=== Конфликты ===")
            for detail in eplan.conflicts:
                lines.append(
                    f"  {detail.status.value}: {detail.external_id} / {detail.full_name}"
                )
        if eplan.validation_errors:
            lines.append("=== Ошибки валидации ===")
            for reason in eplan.validation_errors:
                lines.append(f"  {format_import_reason(reason)}")
    return "\n".join(lines) if lines else "(пусто)"


class TransportImportPlanDetailsDialog(QDialog):
    """Full-screen modal with line-level DirectoryPlan / EmployeePlan diff."""

    def __init__(
        self, validation: ValidationResult, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("transportImportPlanDetailsDialog")
        self.setWindowTitle("Подробности пакета")
        self.setModal(True)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        layout = QVBoxLayout(self)
        text = QTextEdit(objectName="transportImportPlanDetailsText")
        text.setReadOnly(True)
        text.setPlainText(_plan_details_text(validation))
        layout.addWidget(text, stretch=1)
        close_btn = QPushButton("Закрыть", objectName="transportImportPlanDetailsCloseBtn")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)


class TransportImportPanel(QWidget):
    """Multi-step import flow hosted by DatabaseOperationsDialog import tab."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        employees: EmployeeService,
        *,
        db_path: Path | str,
        on_data_changed: OnDataChanged | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("transportImportPanel")
        self._conn = conn
        self._session = session
        self._employees = employees
        self._db_path = Path(db_path)
        self._on_data_changed = on_data_changed
        self._store = TransportKeyStore(conn)
        self._decrypted: DecryptedTransportPackage | None = None
        self._validation: ValidationResult | None = None
        self._resolutions: dict[str, EmployeeMatchResolutionChoice] = {}
        self._confirm_index = 0
        self._confirm_group: QButtonGroup | None = None

        root = QVBoxLayout(self)
        self._stack = QStackedWidget(objectName="transportImportStack")
        root.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_pick_page())
        self._stack.addWidget(self._build_summary_page())
        self._stack.addWidget(self._build_confirm_page())
        self._stack.addWidget(self._build_result_page())
        self._stack.setCurrentIndex(_PAGE_PICK)

    def _build_pick_page(self) -> QWidget:
        page = QWidget(objectName="transportImportPickPage")
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel(
                "Выберите файл transport-пакета для приёма. "
                "После проверки будет показана сводка; применение — только "
                "после подтверждения совпадений (если они есть)."
            )
        )
        btn = QPushButton("Выбрать файл пакета…", objectName="transportImportPickBtn")
        btn.clicked.connect(self._pick_file)
        layout.addWidget(btn)
        layout.addStretch(1)
        return page

    def _build_summary_page(self) -> QWidget:
        page = QWidget(objectName="transportImportSummaryPage")
        layout = QVBoxLayout(page)
        self._summary_label = QLabel(objectName="transportImportSummaryLabel")
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._summary_label)

        self._reasons_label = QLabel(objectName="transportImportReasonsLabel")
        self._reasons_label.setWordWrap(True)
        self._reasons_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._reasons_label)

        row = QHBoxLayout()
        details_btn = QPushButton(
            "Показать подробности", objectName="transportImportDetailsBtn"
        )
        details_btn.clicked.connect(self._show_details)
        row.addWidget(details_btn)
        self._confirm_nav_btn = QPushButton(
            "Подтвердить совпадения…", objectName="transportImportConfirmNavBtn"
        )
        self._confirm_nav_btn.clicked.connect(self._open_confirmations)
        row.addWidget(self._confirm_nav_btn)
        row.addStretch(1)
        self._apply_btn = QPushButton("Применить пакет", objectName="transportImportApplyBtn")
        self._apply_btn.clicked.connect(self._apply_package)
        row.addWidget(self._apply_btn)
        reset_btn = QPushButton("Выбрать другой файл", objectName="transportImportResetBtn")
        reset_btn.clicked.connect(self._reset_to_pick)
        row.addWidget(reset_btn)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _build_confirm_page(self) -> QWidget:
        page = QWidget(objectName="transportImportConfirmPage")
        layout = QVBoxLayout(page)
        self._confirm_progress = QLabel(objectName="transportImportConfirmProgress")
        layout.addWidget(self._confirm_progress)
        self._confirm_header = QLabel(objectName="transportImportConfirmHeader")
        self._confirm_header.setWordWrap(True)
        layout.addWidget(self._confirm_header)
        self._confirm_note = QLabel(_ATTACH_NOTE, objectName="transportImportConfirmNote")
        self._confirm_note.setWordWrap(True)
        layout.addWidget(self._confirm_note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._confirm_choices_host = QWidget(objectName="transportImportConfirmChoices")
        self._confirm_choices_layout = QVBoxLayout(self._confirm_choices_host)
        scroll.setWidget(self._confirm_choices_host)
        layout.addWidget(scroll, stretch=1)
        row = QHBoxLayout()
        back_btn = QPushButton("Назад", objectName="transportImportConfirmBackBtn")
        back_btn.clicked.connect(self._confirm_back)
        row.addWidget(back_btn)
        self._confirm_next_btn = QPushButton(
            "Далее", objectName="transportImportConfirmNextBtn"
        )
        self._confirm_next_btn.clicked.connect(self._confirm_next)
        row.addWidget(self._confirm_next_btn)
        row.addStretch(1)
        to_summary = QPushButton(
            "К сводке", objectName="transportImportConfirmToSummaryBtn"
        )
        to_summary.clicked.connect(lambda: self._stack.setCurrentIndex(_PAGE_SUMMARY))
        row.addWidget(to_summary)
        layout.addLayout(row)
        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget(objectName="transportImportResultPage")
        layout = QVBoxLayout(page)
        self._result_label = QLabel(objectName="transportImportResultLabel")
        self._result_label.setWordWrap(True)
        layout.addWidget(self._result_label)
        again = QPushButton("Импортировать другой пакет", objectName="transportImportAgainBtn")
        again.clicked.connect(self._reset_to_pick)
        layout.addWidget(again)
        layout.addStretch(1)
        return page

    def _pick_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Импорт transport-пакета",
            "",
            "Пакеты (*.hrpkg *.bin *);;Все файлы (*.*)",
        )
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            receive = TransportReceiveAdminService(
                self._conn, self._session, store=self._store
            )
            decrypted = receive.receive_package(raw)
            from services.transport_import_validation import (
                TransportImportValidationService,
            )

            validation = TransportImportValidationService(
                self._conn, self._session, store=self._store
            ).validate_package(decrypted)
        except Exception as exc:  # noqa: BLE001 — surface any crypto/validate error
            QMessageBox.warning(self, "Импорт данных", str(exc))
            return
        self.load_validation(decrypted, validation)

    def load_validation(
        self,
        decrypted: DecryptedTransportPackage,
        validation: ValidationResult,
    ) -> None:
        """Test/UI entry: bind decrypted + validation and show summary."""
        self._decrypted = decrypted
        self._validation = validation
        self._resolutions = {}
        self._confirm_index = 0
        self._refresh_summary()
        self._stack.setCurrentIndex(_PAGE_SUMMARY)

    def _refresh_summary(self) -> None:
        assert self._decrypted is not None and self._validation is not None
        decrypted = self._decrypted
        validation = self._validation
        dir_c, dir_u = _directory_counts(validation)
        emp_c, emp_u, confirmable = _employee_counts(validation)
        self._summary_label.setText(
            f"Disposition: {validation.disposition.value}\n"
            f"Package: {decrypted.package_id}\n"
            f"Direction id: {decrypted.direction_id}\n"
            f"Generation: {decrypted.generation}\n"
            f"Sequence: {decrypted.sequence}\n"
            f"Справочники: создать {dir_c}, обновить {dir_u}\n"
            f"Сотрудники (авто): создать {emp_c}, обновить {emp_u}\n"
            f"Требуют подтверждения: {confirmable}\n\n{_PRE_APPLY_BACKUP_NOTE}"
        )

        reasons_parts: list[str] = []
        if validation.reject_reasons:
            reasons_parts.append("Отказ:\n" + _format_reasons(validation.reject_reasons))
        if validation.confirmation_reasons:
            reasons_parts.append(
                "Подтверждение:\n" + _format_reasons(validation.confirmation_reasons)
            )
        self._reasons_label.setText("\n\n".join(reasons_parts) if reasons_parts else "")

        pending = validation.disposition is ValidationDisposition.PENDING_CONFIRMATION
        ready = validation.disposition is ValidationDisposition.READY_FOR_APPLY
        self._confirm_nav_btn.setVisible(pending)
        self._confirm_nav_btn.setEnabled(pending)
        can_apply = ready or (
            pending and self._all_confirmable_resolved(validation)
        )
        self._apply_btn.setEnabled(can_apply)

    def _all_confirmable_resolved(self, validation: ValidationResult) -> bool:
        plan = validation.employee_plan
        if plan is None or not plan.confirmable:
            return True
        for item in plan.confirmable:
            if str(item.package_row["external_id"]) not in self._resolutions:
                return False
        return True

    def _show_details(self) -> None:
        if self._validation is None:
            return
        TransportImportPlanDetailsDialog(self._validation, parent=self).exec()

    def _open_confirmations(self) -> None:
        if self._validation is None or self._validation.employee_plan is None:
            return
        if not self._validation.employee_plan.confirmable:
            return
        self._confirm_index = 0
        self._render_confirm_item()
        self._stack.setCurrentIndex(_PAGE_CONFIRM)

    def _employee_label(self, employee_id: int) -> str:
        try:
            card = self._employees.get_employee(employee_id)
            return f"{card.full_name} (id={employee_id})"
        except Exception:  # noqa: BLE001
            return f"id={employee_id}"

    def _clear_confirm_choices(self) -> None:
        while self._confirm_choices_layout.count():
            item = self._confirm_choices_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._confirm_group = None

    def _render_confirm_item(self) -> None:
        assert self._validation is not None and self._validation.employee_plan is not None
        items = self._validation.employee_plan.confirmable
        item = items[self._confirm_index]
        external_id = str(item.package_row["external_id"])
        full_name = str(item.package_row["full_name"])
        total = len(items)
        self._confirm_progress.setText(
            f"Запись {self._confirm_index + 1} из {total}"
        )
        self._confirm_header.setText(
            f"{item.match.status.value}: {full_name}\nexternal_id={external_id}"
        )
        self._confirm_note.setVisible(
            item.match.status
            in (EmployeeMatchStatus.LOW, EmployeeMatchStatus.AMBIGUOUS)
        )
        self._clear_confirm_choices()
        group = QButtonGroup(self._confirm_choices_host)
        group.setExclusive(True)
        self._confirm_group = group

        existing = self._resolutions.get(external_id)

        if item.match.status is EmployeeMatchStatus.LOW:
            attach = QRadioButton(_ATTACH_LABEL)
            attach.setObjectName("transportImportChoiceAttach")
            attach.setProperty("resolution", "attach")
            create = QRadioButton(_CREATE_LABEL)
            create.setObjectName("transportImportChoiceCreate")
            create.setProperty("resolution", "create")
            group.addButton(attach)
            group.addButton(create)
            self._confirm_choices_layout.addWidget(attach)
            self._confirm_choices_layout.addWidget(create)
            if existing is not None:
                if existing.action is EmployeeMatchResolution.ATTACH_EXISTING:
                    attach.setChecked(True)
                else:
                    create.setChecked(True)
        elif item.match.status is EmployeeMatchStatus.AMBIGUOUS:
            for candidate_id in item.match.candidate_employee_ids:
                radio = QRadioButton(self._employee_label(candidate_id))
                radio.setObjectName(f"transportImportChoiceCandidate_{candidate_id}")
                radio.setProperty("resolution", "attach")
                radio.setProperty("attach_employee_id", candidate_id)
                group.addButton(radio)
                self._confirm_choices_layout.addWidget(radio)
                if (
                    existing is not None
                    and existing.action is EmployeeMatchResolution.ATTACH_EXISTING
                    and existing.attach_employee_id == candidate_id
                ):
                    radio.setChecked(True)
            create = QRadioButton(_CREATE_LABEL)
            create.setObjectName("transportImportChoiceCreate")
            create.setProperty("resolution", "create")
            group.addButton(create)
            self._confirm_choices_layout.addWidget(create)
            if (
                existing is not None
                and existing.action is EmployeeMatchResolution.CREATE_NEW
            ):
                create.setChecked(True)
        self._confirm_choices_layout.addStretch(1)

        last = self._confirm_index >= total - 1
        self._confirm_next_btn.setText("К сводке" if last else "Далее")

    def _capture_current_choice(self) -> bool:
        assert self._validation is not None and self._validation.employee_plan is not None
        item = self._validation.employee_plan.confirmable[self._confirm_index]
        external_id = str(item.package_row["external_id"])
        if self._confirm_group is None:
            return False
        checked = self._confirm_group.checkedButton()
        if checked is None:
            QMessageBox.information(
                self, "Подтверждение", "Выберите вариант для этой записи."
            )
            return False
        kind = checked.property("resolution")
        if kind == "create":
            self._resolutions[external_id] = EmployeeMatchResolutionChoice(
                action=EmployeeMatchResolution.CREATE_NEW
            )
        else:
            attach_id = checked.property("attach_employee_id")
            self._resolutions[external_id] = EmployeeMatchResolutionChoice(
                action=EmployeeMatchResolution.ATTACH_EXISTING,
                attach_employee_id=int(attach_id) if attach_id is not None else None,
            )
        return True

    def _confirm_back(self) -> None:
        if self._confirm_index <= 0:
            self._stack.setCurrentIndex(_PAGE_SUMMARY)
            return
        if not self._capture_current_choice():
            return
        self._confirm_index -= 1
        self._render_confirm_item()

    def _confirm_next(self) -> None:
        if not self._capture_current_choice():
            return
        assert self._validation is not None and self._validation.employee_plan is not None
        total = len(self._validation.employee_plan.confirmable)
        if self._confirm_index >= total - 1:
            self._refresh_summary()
            self._stack.setCurrentIndex(_PAGE_SUMMARY)
            return
        self._confirm_index += 1
        self._render_confirm_item()

    def _apply_package(self) -> None:
        if self._decrypted is None or self._validation is None:
            return
        if self._validation.disposition not in (
            ValidationDisposition.READY_FOR_APPLY,
            ValidationDisposition.PENDING_CONFIRMATION,
        ):
            QMessageBox.warning(self, "Импорт данных", "Пакет нельзя применить.")
            return
        if not self._all_confirmable_resolved(self._validation):
            QMessageBox.information(
                self,
                "Импорт данных",
                "Сначала подтвердите все записи с неоднозначным совпадением.",
            )
            return
        try:
            apply_svc = TransportImportApplyAdminService(
                self._conn,
                self._session,
                store=self._store,
                db_path=self._db_path,
            )
            result = apply_svc.apply_validated_package(
                self._decrypted,
                self._validation,
                resolutions=self._resolutions or None,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Импорт данных", str(exc))
            return
        self._result_label.setText(
            f"Пакет применён.\n"
            f"package_id={result.package_id}\n"
            f"sequence={result.sequence}\n"
            f"direction_id={result.direction_id}"
        )
        self._stack.setCurrentIndex(_PAGE_RESULT)
        if self._on_data_changed is not None:
            self._on_data_changed()

    def _reset_to_pick(self) -> None:
        self._decrypted = None
        self._validation = None
        self._resolutions = {}
        self._confirm_index = 0
        self._clear_confirm_choices()
        self._stack.setCurrentIndex(_PAGE_PICK)


__all__ = [
    "TransportImportPanel",
    "TransportImportPlanDetailsDialog",
]
