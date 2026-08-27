"""Integration: форма карточки → RosterService (ТЗ §3.1 / §3.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.roster import RosterService
from tests.fixtures.synthetic import seed_synthetic_org
from ui.employee_card_form import EmployeeCardDialog


@pytest.mark.acceptance
def test_create_via_form_appears_in_roster(qtbot, tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-27T11:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=lambda: "2026-08-27T11:00:00Z")
    directories = DirectoryService(conn, session, clock=lambda: "2026-08-27T11:00:00Z")
    dialog = EmployeeCardDialog(employees, directories, session)
    qtbot.addWidget(dialog)
    dialog._name.setText("Кузнецова Ольга")
    dialog._position.setCurrentIndex(1)
    dialog._branch.setCurrentIndex(1)
    dialog._department.setCurrentIndex(1)
    dialog._division.setCurrentIndex(1)
    dialog._employment.setCurrentIndex(1)
    dialog._submit()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.saved_employee_id is not None
    roster = RosterService(conn, session, clock=lambda: "2026-08-27T11:00:00Z")
    names = {row.full_name for row in roster.list_rows()}
    assert "Кузнецова Ольга" in names
    created = conn.execute(
        "SELECT COUNT(*) FROM user_action_log WHERE action_type = 'employee.create'"
        " AND entity_id = ?",
        (dialog.saved_employee_id,),
    ).fetchone()[0]
    assert created == 1
    conn.close()
