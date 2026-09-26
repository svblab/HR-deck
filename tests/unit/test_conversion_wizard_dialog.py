"""UI: EPIC-018 conversion wizard (ADR-0012)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)

from data.import_sessions import ImportSessionRepository
from domain.employee import EmployeeCreateInput
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.employee_conversion import EmployeeConversionService
from services.employees import EmployeeService
from services.import_conversion_ingest import ImportConversionIngestResult
from tests.fixtures.synthetic import seed_synthetic_org
from ui.conversion_wizard_dialog import ConversionWizardDialog, run_conversion_wizard_flow
from ui.main_window import MainWindow


def _open(tmp_path: Path):
    clock = lambda: "2026-09-25T10:00:00Z"  # noqa: E731
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=clock)
    directories = DirectoryService(conn, session, clock=clock)
    sessions = ImportSessionRepository(conn)
    conversion = EmployeeConversionService(conn, session, employees, sessions=sessions)
    return conn, session, employees, directories, sessions, conversion, ids


def _stage_session(sessions: ImportSessionRepository, conn, *, rows: list[dict]) -> int:
    session_id = sessions.create_session(
        file_content_hash="a" * 64, last_accessed_at="2026-09-25T09:00:00Z"
    )
    for idx, values in enumerate(rows, start=2):
        sessions.insert_row(
            session_id=session_id,
            source_row_number=idx,
            values_json=json.dumps(values, ensure_ascii=False),
        )
    conn.commit()
    return session_id


def _fill_required_card(dialog: ConversionWizardDialog, ids: dict[str, int]) -> None:
    card = dialog._card
    card.findChild(QLineEdit, "fieldFullName").setText("Новый Конверт")
    _select(card, "fieldBranch", ids["branch_id"])
    _select(card, "fieldDepartment", ids["department_id"])
    _select(card, "fieldDivision", ids["division_id"])
    _select(card, "fieldPosition", ids["position_engineer_id"])
    _select(card, "fieldEmploymentType", 1)


def _select(card, object_name: str, entity_id: int) -> None:
    combo = card.findChild(QComboBox, object_name)
    assert combo is not None
    idx = combo.findData(entity_id)
    assert idx >= 0
    combo.setCurrentIndex(idx)


@pytest.mark.acceptance
def test_main_window_database_operations_entry_with_import_permissions(
    qtbot, tmp_path: Path
) -> None:
    conn, session, _employees, _directories, _s, _c, _ids = _open(tmp_path)
    window = MainWindow(conn=conn, session=session, db_path=tmp_path / "app.db")
    qtbot.addWidget(window)
    tool_btn = window.findChild(QToolButton, "databaseOperationsBtn")
    assert tool_btn is not None and tool_btn.isEnabled()
    conn.close()


@pytest.mark.acceptance
def test_wizard_prefills_first_row(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions,
        conn,
        rows=[{"full_name": "Иванов Иван", "branch": "Филиал Север (тест)"}],
    )
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T10:00:00Z",
    )
    qtbot.addWidget(dialog)
    name = dialog._card.findChild(QLineEdit, "fieldFullName")
    assert name is not None and name.text() == "Иванов Иван"
    conn.close()


@pytest.mark.acceptance
def test_invalid_save_stays_on_row(qtbot, tmp_path: Path, monkeypatch) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions, conn, rows=[{"full_name": "Иванов Иван", "branch": ""}]
    )
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T10:00:00Z",
    )
    qtbot.addWidget(dialog)
    saves: list[int] = []
    monkeypatch.setattr(
        conversion,
        "save_row",
        lambda **kwargs: saves.append(kwargs["row_id"]) or 1,
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_a, text="", **_k: warnings.append(str(text)) or QMessageBox.StandardButton.Ok,
    )
    save_btn = dialog.findChild(QPushButton, "conversionWizardSaveBtn")
    qtbot.mouseClick(save_btn, Qt.MouseButton.LeftButton)
    assert saves == []
    assert len(sessions.list_rows(session_id)) == 1
    assert warnings
    conn.close()


@pytest.mark.acceptance
def test_save_advances_to_next_row(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions,
        conn,
        rows=[
            {"full_name": "Первый", "branch": "Филиал Север (тест)"},
            {"full_name": "Второй", "branch": "Филиал Север (тест)"},
        ],
    )
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T10:00:00Z",
    )
    qtbot.addWidget(dialog)
    _fill_required_card(dialog, ids)
    dialog._card.findChild(QLineEdit, "fieldFullName").setText("Первый")
    save_btn = dialog.findChild(QPushButton, "conversionWizardSaveBtn")
    qtbot.mouseClick(save_btn, Qt.MouseButton.LeftButton)
    remaining = sessions.list_rows(session_id)
    assert len(remaining) == 1
    assert json.loads(remaining[0].values_json)["full_name"] == "Второй"
    conn.close()


@pytest.mark.acceptance
def test_skip_calls_service_and_advances(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions,
        conn,
        rows=[
            {"full_name": "Первый"},
            {"full_name": "Второй"},
        ],
    )
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T11:00:00Z",
    )
    qtbot.addWidget(dialog)
    before_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    skip_btn = dialog.findChild(QPushButton, "conversionWizardSkipBtn")
    qtbot.mouseClick(skip_btn, Qt.MouseButton.LeftButton)
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before_emp
    assert len(sessions.list_rows(session_id)) == 1
    conn.close()


@pytest.mark.acceptance
def test_duplicate_warning_shown(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    duplicate_name = "Уникальный Дубликат Тест"
    employees.create_employee(
        EmployeeCreateInput(
            full_name=duplicate_name,
            position_id=ids["position_engineer_id"],
            branch_id=ids["branch_id"],
            department_id=ids["department_id"],
            division_id=ids["division_id"],
            employment_type_id=1,
        )
    )
    session_id = _stage_session(
        sessions, conn, rows=[{"full_name": duplicate_name}]
    )
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T10:00:00Z",
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitForWindowShown(dialog)
    assert dialog._duplicate_match_ids
    assert "дубль" in dialog._duplicate_banner.text().casefold()
    conn.close()


@pytest.mark.acceptance
def test_user_can_edit_draft_before_save(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions, conn, rows=[{"full_name": "Старое Имя", "branch": "Филиал Север (тест)"}]
    )
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T10:00:00Z",
    )
    qtbot.addWidget(dialog)
    edited = "Отредактированное Имя"
    dialog._card.findChild(QLineEdit, "fieldFullName").setText(edited)
    _fill_required_card(dialog, ids)
    dialog._card.findChild(QLineEdit, "fieldFullName").setText(edited)
    qtbot.mouseClick(
        dialog.findChild(QPushButton, "conversionWizardSaveBtn"), Qt.MouseButton.LeftButton
    )
    row = conn.execute(
        "SELECT full_name FROM employees ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row[0] == edited
    conn.close()


@pytest.mark.acceptance
def test_save_service_failure_does_not_advance(qtbot, tmp_path: Path, monkeypatch) -> None:
    from services.employee_conversion import EmployeeConversionError

    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions,
        conn,
        rows=[{"full_name": "Первый", "branch": "Филиал Север (тест)"}, {"full_name": "Второй"}],
    )
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T10:00:00Z",
    )
    qtbot.addWidget(dialog)
    _fill_required_card(dialog, ids)

    def _boom(**_kwargs):
        raise EmployeeConversionError("fail")

    monkeypatch.setattr(conversion, "save_row", _boom)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_a, **_k: QMessageBox.StandardButton.Ok,
    )
    qtbot.mouseClick(
        dialog.findChild(QPushButton, "conversionWizardSaveBtn"), Qt.MouseButton.LeftButton
    )
    assert len(sessions.list_rows(session_id)) == 2
    conn.close()


@pytest.mark.acceptance
def test_skip_service_failure_does_not_advance(qtbot, tmp_path: Path, monkeypatch) -> None:
    from services.employee_conversion import EmployeeConversionError

    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions,
        conn,
        rows=[{"full_name": "Первый"}, {"full_name": "Второй"}],
    )
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T10:00:00Z",
    )
    qtbot.addWidget(dialog)

    def _boom(**_kwargs):
        raise EmployeeConversionError("fail")

    monkeypatch.setattr(conversion, "skip_row", _boom)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_a, **_k: QMessageBox.StandardButton.Ok,
    )
    qtbot.mouseClick(
        dialog.findChild(QPushButton, "conversionWizardSkipBtn"), Qt.MouseButton.LeftButton
    )
    assert len(sessions.list_rows(session_id)) == 2
    conn.close()


@pytest.mark.acceptance
def test_last_row_save_finishes_wizard(qtbot, tmp_path: Path) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions, conn, rows=[{"full_name": "Единственный", "branch": "Филиал Север (тест)"}]
    )
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T10:00:00Z",
    )
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog.accepted, timeout=3000):
        _fill_required_card(dialog, ids)
        dialog._card.findChild(QLineEdit, "fieldFullName").setText("Единственный")
        qtbot.mouseClick(
            dialog.findChild(QPushButton, "conversionWizardSaveBtn"), Qt.MouseButton.LeftButton
        )
    assert sessions.get_by_file_content_hash("a" * 64) is None
    conn.close()


@pytest.mark.acceptance
def test_duplicate_reference_is_read_only(qtbot, tmp_path: Path, monkeypatch) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    duplicate_name = "Только Для Справки"
    employees.create_employee(
        EmployeeCreateInput(
            full_name=duplicate_name,
            position_id=ids["position_engineer_id"],
            branch_id=ids["branch_id"],
            department_id=ids["department_id"],
            division_id=ids["division_id"],
            employment_type_id=1,
        )
    )
    session_id = _stage_session(sessions, conn, rows=[{"full_name": duplicate_name}])
    dialog = ConversionWizardDialog(
        conn,
        session,
        employees,
        directories,
        conversion=conversion,
        sessions=sessions,
        session_id=session_id,
        clock=lambda: "2026-09-25T10:00:00Z",
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitForWindowShown(dialog)
    opened: list[object] = []

    def _capture_exec(self):
        opened.append(self)
        for widget in self.findChildren(QLineEdit):
            assert not widget.isEnabled()
        for widget in self.findChildren(QComboBox):
            assert not widget.isEnabled()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", _capture_exec)
    qtbot.mouseClick(
        dialog.findChild(QPushButton, "conversionViewDuplicateBtn"), Qt.MouseButton.LeftButton
    )
    assert len(opened) == 1
    conn.close()


@pytest.mark.acceptance
def test_resume_path_touches_session(qtbot, tmp_path: Path, monkeypatch) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions, conn, rows=[{"full_name": "Иванов", "branch": "Филиал Север (тест)"}]
    )
    before = sessions.get_by_file_content_hash("a" * 64)
    assert before is not None
    ingest_mock = MagicMock()
    ingest_mock.ingest_file.return_value = ImportConversionIngestResult(
        session_id=session_id,
        file_content_hash="a" * 64,
        resumed=True,
        staged_row_count=1,
    )
    monkeypatch.setattr(
        "ui.conversion_wizard_dialog.ImportConversionIngestService",
        lambda *args, **kwargs: ingest_mock,
    )
    monkeypatch.setattr(
        "ui.conversion_wizard_dialog.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(tmp_path / "f.csv"), ""),
    )
    monkeypatch.setattr(
        "ui.conversion_wizard_dialog.ConversionWizardDialog.exec",
        lambda self: QDialog.DialogCode.Rejected,
    )
    tick = lambda: "2026-09-25T10:00:00Z"  # noqa: E731
    run_conversion_wizard_flow(
        QWidget(), conn, session, employees, directories, clock=tick
    )
    after = sessions.get_by_file_content_hash("a" * 64)
    assert after is not None
    assert after.last_accessed_at == tick()
    assert after.last_accessed_at != before.last_accessed_at
    conn.close()


@pytest.mark.acceptance
def test_run_flow_calls_ingest_service(qtbot, tmp_path: Path, monkeypatch) -> None:
    conn, session, employees, directories, sessions, conversion, ids = _open(tmp_path)
    session_id = _stage_session(
        sessions, conn, rows=[{"full_name": "Иванов", "branch": "Филиал Север (тест)"}]
    )
    ingest_mock = MagicMock()
    ingest_mock.ingest_file.return_value = ImportConversionIngestResult(
        session_id=session_id,
        file_content_hash="b" * 64,
        resumed=True,
        staged_row_count=1,
    )
    monkeypatch.setattr(
        "ui.conversion_wizard_dialog.ImportConversionIngestService",
        lambda *args, **kwargs: ingest_mock,
    )
    monkeypatch.setattr(
        "ui.conversion_wizard_dialog.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(tmp_path / "f.csv"), ""),
    )
    monkeypatch.setattr(
        "ui.conversion_wizard_dialog.ConversionWizardDialog.exec",
        lambda self: QDialog.DialogCode.Rejected,
    )
    assert (
        run_conversion_wizard_flow(
            QWidget(),
            conn,
            session,
            employees,
            directories,
        )
        is False
    )
    ingest_mock.ingest_file.assert_called_once()
    conn.close()
