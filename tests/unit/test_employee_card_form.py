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
