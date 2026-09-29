"""ADR-0014: automatic verified backups before conversion and transport apply."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from data.backup_io import default_backups_dir
from data.keywrap import keywrap_path_for
from services.backup import BackupError, BackupService
from services.bootstrap import BootstrapService
from services.employee_conversion import EmployeeConversionError, EmployeeConversionService
from services.employees import EmployeeService
from services.transport_import_apply import TransportImportApplyService
from services.transport_import_validation import (
    TransportImportValidationService,
    ValidationDisposition,
)
from tests.fixtures.synthetic import seed_synthetic_org
from tests.integration.test_employee_conversion_service import _employee_payload
from tests.integration.test_transport_import_apply import (
    _admin_open,
    _decrypted,
    _ensure_inbound_direction,
)

_T0 = "2026-09-25T12:00:00Z"
_HASH = "d" * 64
_T1 = "2026-09-25T11:00:00Z"


def test_conversion_pre_backup_once_per_session(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    conversion = EmployeeConversionService(
        conn, session, employees, db_path=db
    )
    session_id, row_a = _stage_row_custom(conn, row_number=2)
    row_b = _insert_row(conn, session_id, row_number=3)

    conversion.save_row(
        session_id=session_id,
        row_id=row_a,
        data=_employee_payload(ids, full_name="Первый"),
        last_accessed_at=_T1,
    )
    backups_after_first = list(default_backups_dir(db.parent).glob("pre-conversion-*.db"))
    assert len(backups_after_first) == 1
    assert keywrap_path_for(backups_after_first[0]).is_file()

    conversion.save_row(
        session_id=session_id,
        row_id=row_b,
        data=_employee_payload(ids, full_name="Второй"),
        last_accessed_at=_T1,
    )
    backups_after_second = list(default_backups_dir(db.parent).glob("pre-conversion-*.db"))
    assert len(backups_after_second) == 1
    conn.close()


def test_conversion_aborts_when_pre_backup_fails(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    ids = seed_synthetic_org(conn)
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    conversion = EmployeeConversionService(
        conn, session, employees, db_path=db
    )
    session_id, row_id = _stage_row_custom(conn, row_number=2)
    before = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]

    def _fail(*args, **kwargs):
        raise BackupError("disk full")

    monkeypatch.setattr(
        "services.backup.BackupService.create_pre_apply_backup",
        _fail,
    )
    with pytest.raises(EmployeeConversionError, match="disk full"):
        conversion.save_row(
            session_id=session_id,
            row_id=row_id,
            data=_employee_payload(ids),
            last_accessed_at=_T1,
        )
    after = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    assert after == before
    conn.close()


def test_transport_pre_import_backup_before_apply(tmp_path: Path) -> None:
    conn, session, store, db = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    package_id = str(uuid.uuid4())
    tables = {
        "branches": [
            {
                "id": 1,
                "external_id": str(uuid.uuid4()),
                "name": "Филиал А",
                "is_archived": False,
                "created_at": _T0,
                "updated_at": _T0,
            }
        ]
    }
    decrypted = _decrypted(
        direction_id=direction_id,
        sequence=1,
        package_id=package_id,
        tables=tables,
    )
    validation = TransportImportValidationService(conn, session, store=store).validate_package(
        decrypted
    )
    assert validation.disposition is ValidationDisposition.READY_FOR_APPLY

    apply_svc = TransportImportApplyService(conn, session, store=store, db_path=db)
    apply_svc.apply_validated_package(decrypted, validation)

    backups = list(default_backups_dir(db.parent).glob("pre-import-*.db"))
    assert len(backups) == 1
    BackupService(conn, session, db_path=db).verify_backup(backups[0])
    conn.close()


def test_transport_apply_aborts_when_pre_backup_fails(tmp_path: Path, monkeypatch) -> None:
    conn, session, store, db = _admin_open(tmp_path)
    direction_id = _ensure_inbound_direction(store, conn)
    decrypted = _decrypted(
        direction_id=direction_id,
        sequence=1,
        package_id=str(uuid.uuid4()),
        tables={
            "branches": [
                {
                    "id": 1,
                    "external_id": str(uuid.uuid4()),
                    "name": "Филиал А",
                    "is_archived": False,
                    "created_at": _T0,
                    "updated_at": _T0,
                }
            ]
        },
    )
    validation = TransportImportValidationService(conn, session, store=store).validate_package(
        decrypted
    )
    before = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]

    def _fail(self, prefix, *, log_event):
        raise BackupError("simulated pre-import failure")

    monkeypatch.setattr(BackupService, "create_pre_apply_backup", _fail)

    apply_svc = TransportImportApplyService(conn, session, store=store, db_path=db)
    with pytest.raises(BackupError, match="simulated"):
        apply_svc.apply_validated_package(decrypted, validation)
    after = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
    assert after == before

    rows = conn.execute(
        "SELECT event_type, message FROM technical_events"
        " WHERE event_type = 'backup.pre_import'"
    ).fetchall()
    assert not rows
    conn.close()


def test_pre_backup_failure_logs_technical_event(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "app.db"
    conn, session, _code = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    backup = BackupService(conn, session, db_path=db, clock=lambda: _T0)

    def _fail_verify(path, key):
        raise OSError("verify boom")

    monkeypatch.setattr("services.backup.verify_database_file", _fail_verify)
    with pytest.raises(BackupError, match="pre-apply backup failed"):
        backup.create_pre_apply_backup("pre-import", log_event="backup.pre_import")
    row = conn.execute(
        "SELECT message FROM technical_events WHERE event_type = 'backup.pre_import'"
    ).fetchone()
    assert row is not None
    assert "pre-backup failed" in row[0]
    assert "verify boom" in row[0]
    conn.close()


def _stage_row_custom(conn, *, row_number: int) -> tuple[int, int]:
    from data.import_sessions import ImportSessionRepository

    sessions = ImportSessionRepository(conn)
    session_id = sessions.create_session(file_content_hash=_HASH, last_accessed_at=_T0)
    row_id = sessions.insert_row(
        session_id=session_id,
        source_row_number=row_number,
        values_json=json.dumps({"full_name": "Новый Сотрудник"}),
    )
    conn.commit()
    return session_id, row_id


def _insert_row(conn, session_id: int, *, row_number: int) -> int:
    from data.import_sessions import ImportSessionRepository

    sessions = ImportSessionRepository(conn)
    row_id = sessions.insert_row(
        session_id=session_id,
        source_row_number=row_number,
        values_json=json.dumps({"full_name": "Ещё один"}),
    )
    conn.commit()
    return row_id
