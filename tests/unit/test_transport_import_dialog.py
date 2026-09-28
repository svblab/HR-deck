"""UI: ADR-0013 transport import confirmation gate (EPIC-021 Checkpoint 3)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QRadioButton

from data.employees import EmployeeRepository
from domain.employee import EmployeeCreateInput
from domain.employee_reconciliation import (
    EmployeeMatchCandidate,
    EmployeeMatchStatus,
)
from domain.import_errors import ImportErrorCode
from domain.transport import PackageClassification
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.directory_sync_import import DirectoryPlan
from services.employee_sync_import import EmployeePlan, _EmployeePlanItem
from services.employees import EmployeeService
from services.transport_import_apply import ApplyResult
from services.transport_import_validation import (
    FreshnessClass,
    ValidationDisposition,
    ValidationResult,
)
from services.transport_receive import DecryptedTransportPackage
from ui.database_operations_dialog import DatabaseOperationsDialog
from ui.transport_import_dialog import TransportImportPanel

_T0 = "2026-09-28T12:00:00Z"


def _open(tmp_path: Path):
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    directories = DirectoryService(conn, session, clock=lambda: _T0)
    return conn, session, employees, directories


def _decrypted(*, direction_id: int = 1, sequence: int = 1) -> DecryptedTransportPackage:
    return DecryptedTransportPackage(
        payload=json.dumps({}).encode("utf-8"),
        sender_installation_id="sender",
        recipient_installation_id="recipient",
        direction_id=direction_id,
        generation=0,
        sequence=sequence,
        package_id=str(uuid.uuid4()),
        envelope_key_id="bootstrap",
        next_wk_key_id=str(uuid.uuid4()),
        next_wk_material=b"\x03" * 32,
    )


def _ready_validation() -> ValidationResult:
    return ValidationResult(
        freshness=FreshnessClass.NEW,
        disposition=ValidationDisposition.READY_FOR_APPLY,
        directory_plan=DirectoryPlan(),
        employee_plan=EmployeePlan(),
    )


def _rejected_validation() -> ValidationResult:
    return ValidationResult(
        freshness=FreshnessClass.STALE,
        disposition=ValidationDisposition.REJECTED,
        directory_plan=None,
        employee_plan=None,
        reject_reasons=(
            (ImportErrorCode.PACKAGE_STALE_SEQUENCE, "stale or out-of-sequence package"),
        ),
    )


def _pending_low_ambiguous(
    *,
    low_row: dict[str, object],
    low_matched_id: int,
    amb_row: dict[str, object],
    amb_candidates: tuple[int, ...],
) -> ValidationResult:
    confirmable = [
        _EmployeePlanItem(
            match=EmployeeMatchCandidate(
                package_row=low_row,
                status=EmployeeMatchStatus.LOW,
                matched_employee_id=low_matched_id,
                candidate_employee_ids=(low_matched_id,),
            ),
            package_row=low_row,
        ),
        _EmployeePlanItem(
            match=EmployeeMatchCandidate(
                package_row=amb_row,
                status=EmployeeMatchStatus.AMBIGUOUS,
                matched_employee_id=None,
                candidate_employee_ids=amb_candidates,
            ),
            package_row=amb_row,
        ),
    ]
    plan = EmployeePlan(confirmable=confirmable)
    return ValidationResult(
        freshness=FreshnessClass.NEW,
        disposition=ValidationDisposition.PENDING_CONFIRMATION,
        directory_plan=DirectoryPlan(),
        employee_plan=plan,
        confirmation_reasons=(
            (
                ImportErrorCode.EMPLOYEE_MATCH_LOW,
                f"low: external_id={low_row['external_id']} name={low_row['full_name']!r}",
            ),
            (
                ImportErrorCode.EMPLOYEE_MATCH_AMBIGUOUS,
                f"ambiguous: external_id={amb_row['external_id']} "
                f"name={amb_row['full_name']!r}",
            ),
        ),
    )


def test_rejected_path_renders_code_message_and_disables_apply(
    qtbot, tmp_path: Path
) -> None:
    conn, session, employees, _directories = _open(tmp_path)
    panel = TransportImportPanel(conn, session, employees)
    qtbot.addWidget(panel)
    panel.load_validation(_decrypted(), _rejected_validation())

    reasons = panel.findChild(QLabel, "transportImportReasonsLabel")
    assert reasons is not None
    assert "IMP-001: stale or out-of-sequence package" in reasons.text()
    assert "('IMP-001'" not in reasons.text()

    apply_btn = panel.findChild(QPushButton, "transportImportApplyBtn")
    assert apply_btn is not None
    assert not apply_btn.isEnabled()
    conn.close()


def test_ready_for_apply_happy_path(qtbot, tmp_path: Path) -> None:
    conn, session, employees, _directories = _open(tmp_path)
    changed: list[int] = []
    panel = TransportImportPanel(
        conn, session, employees, on_data_changed=lambda: changed.append(1)
    )
    qtbot.addWidget(panel)
    decrypted = _decrypted()
    panel.load_validation(decrypted, _ready_validation())

    apply_btn = panel.findChild(QPushButton, "transportImportApplyBtn")
    assert apply_btn is not None and apply_btn.isEnabled()

    fake_result = ApplyResult(
        package_id=decrypted.package_id,
        direction_id=decrypted.direction_id,
        sequence=decrypted.sequence,
        classification=PackageClassification.ACCEPTED,
    )
    with patch(
        "ui.transport_import_dialog.TransportImportApplyAdminService"
    ) as apply_cls:
        apply_cls.return_value.apply_validated_package.return_value = fake_result
        qtbot.mouseClick(apply_btn, Qt.MouseButton.LeftButton)
        apply_cls.return_value.apply_validated_package.assert_called_once()

    result = panel.findChild(QLabel, "transportImportResultLabel")
    assert result is not None
    assert "package_id=" in result.text()
    assert changed == [1]
    conn.close()


def test_pending_confirmation_low_and_ambiguous(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories = _open(tmp_path)
    branch_id = directories.create_branch("Филиал")
    dept_id = directories.create_department(branch_id, "Деп")
    div_id = directories.create_division(branch_id, dept_id, "Отдел")
    pos_id = directories.create_position(branch_id, "Инженер")
    low_id = employees.create_employee(
        EmployeeCreateInput(
            full_name="Сидоров Сидор Сидорович",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=dept_id,
            division_id=div_id,
            employment_type_id=1,
        )
    )
    amb_a = employees.create_employee(
        EmployeeCreateInput(
            full_name="Новиков Николай Николаевич",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=dept_id,
            division_id=div_id,
            employment_type_id=1,
        )
    )
    amb_b = employees.create_employee(
        EmployeeCreateInput(
            full_name="Новиков Николай Николаевич",
            position_id=pos_id,
            branch_id=branch_id,
            department_id=dept_id,
            division_id=div_id,
            employment_type_id=1,
        )
    )
    low_ext = str(uuid.uuid4())
    amb_ext = str(uuid.uuid4())
    low_row = {
        "external_id": low_ext,
        "full_name": "Сидоров Сидор Сидорович",
    }
    amb_row = {
        "external_id": amb_ext,
        "full_name": "Новиков Николай Николаевич",
    }
    validation = _pending_low_ambiguous(
        low_row=low_row,
        low_matched_id=low_id,
        amb_row=amb_row,
        amb_candidates=(amb_a, amb_b),
    )

    panel = TransportImportPanel(conn, session, employees)
    qtbot.addWidget(panel)
    panel.load_validation(_decrypted(), validation)

    reasons = panel.findChild(QLabel, "transportImportReasonsLabel")
    assert reasons is not None
    assert "IMP-018:" in reasons.text()
    assert "IMP-019:" in reasons.text()

    apply_btn = panel.findChild(QPushButton, "transportImportApplyBtn")
    assert apply_btn is not None
    assert not apply_btn.isEnabled()

    nav = panel.findChild(QPushButton, "transportImportConfirmNavBtn")
    assert nav is not None and nav.isEnabled() and not nav.isHidden()
    qtbot.mouseClick(nav, Qt.MouseButton.LeftButton)

    note = panel.findChild(QLabel, "transportImportConfirmNote")
    assert note is not None
    assert "не запоминается" in note.text()

    attach = panel.findChild(QRadioButton, "transportImportChoiceAttach")
    assert attach is not None
    assert "только для этого импорта" in attach.text()
    attach.setChecked(True)
    next_btn = panel.findChild(QPushButton, "transportImportConfirmNextBtn")
    assert next_btn is not None
    qtbot.mouseClick(next_btn, Qt.MouseButton.LeftButton)

    candidate = panel.findChild(QRadioButton, f"transportImportChoiceCandidate_{amb_b}")
    assert candidate is not None
    candidate.setChecked(True)
    qtbot.mouseClick(next_btn, Qt.MouseButton.LeftButton)

    assert apply_btn.isEnabled()
    assert low_ext in panel._resolutions
    assert amb_ext in panel._resolutions
    assert EmployeeRepository(conn).get(low_id) is not None
    conn.close()


def test_import_tab_hosts_transport_panel(qtbot, tmp_path: Path) -> None:
    from services.backup import BackupService
    from services.status_history import StatusHistoryService

    conn, session, employees, directories = _open(tmp_path)
    db = tmp_path / "app.db"
    dialog = DatabaseOperationsDialog(
        conn,
        session,
        backup=BackupService(conn, session, db_path=db, clock=lambda: _T0),
        employees=employees,
        directories=directories,
        status_history=StatusHistoryService(conn, session, clock=lambda: _T0),
    )
    qtbot.addWidget(dialog)
    panel = dialog.findChild(TransportImportPanel, "transportImportPanel")
    assert panel is not None
    pick = dialog.findChild(QPushButton, "transportImportPickBtn")
    assert pick is not None
    conn.close()
