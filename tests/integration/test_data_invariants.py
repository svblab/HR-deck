"""Негативные тесты инвариантов оргструктуры и периодов статусов."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from domain.org_structure import (
    DepartmentRef,
    DivisionRef,
    OrgAssignment,
    OrgConsistencyError,
    validate_org_assignment,
)
from domain.status_periods import StatusPeriod, StatusPeriodError, validate_new_status_period
from tests.fixtures.synthetic import seed_synthetic_org

_NOW = "2026-08-01T10:00:00Z"


def _db(tmp_path: Path):
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    ids = seed_synthetic_org(conn)
    return conn, ids


@pytest.mark.acceptance
def test_domain_rejects_mismatched_org_assignment() -> None:
    with pytest.raises(OrgConsistencyError):
        validate_org_assignment(
            OrgAssignment(branch_id=1, department_id=1),
            DepartmentRef(id=1, branch_id=2),
        )
    with pytest.raises(OrgConsistencyError):
        validate_org_assignment(
            OrgAssignment(branch_id=1, department_id=1, division_id=1),
            DepartmentRef(id=1, branch_id=1),
            DivisionRef(id=1, department_id=99),
        )


@pytest.mark.acceptance
def test_db_rejects_employee_with_foreign_department(tmp_path: Path) -> None:
    conn, _ids = _db(tmp_path)
    conn.execute(
        "INSERT INTO branches (id, name, is_archived, created_at, updated_at) "
        "VALUES (2, 'Other', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO departments (id, branch_id, name, is_archived, created_at, updated_at) "
        "VALUES (2, 2, 'Other dept', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.commit()
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute(
            "INSERT INTO employees ("
            " full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, is_archived, created_at, updated_at"
            ") VALUES ('X', 1, 1, 2, NULL, 1, 0, ?, ?)",
            (_NOW, _NOW),
        )
    conn.close()


@pytest.mark.acceptance
def test_db_rejects_employee_with_foreign_division(tmp_path: Path) -> None:
    conn, _ids = _db(tmp_path)
    conn.execute(
        "INSERT INTO departments (id, branch_id, name, is_archived, created_at, updated_at) "
        "VALUES (2, 1, 'Dept B', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO divisions (id, department_id, name, is_archived, created_at, updated_at) "
        "VALUES (2, 2, 'Div B', 0, ?, ?)",
        (_NOW, _NOW),
    )
    conn.commit()
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute(
            "INSERT INTO employees ("
            " full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, is_archived, created_at, updated_at"
            ") VALUES ('X', 1, 1, 1, 2, 1, 0, ?, ?)",
            (_NOW, _NOW),
        )
    conn.close()


@pytest.mark.acceptance
def test_domain_rejects_reversed_and_overlapping_periods() -> None:
    with pytest.raises(StatusPeriodError, match="start_date"):
        validate_new_status_period([], StatusPeriod("2026-08-10", "2026-08-01"))

    existing = [StatusPeriod("2026-08-01", "2026-08-10")]
    with pytest.raises(StatusPeriodError, match="overlapping"):
        validate_new_status_period(existing, StatusPeriod("2026-08-05", "2026-08-12"))

    existing_open = [StatusPeriod("2026-08-01", None)]
    with pytest.raises(StatusPeriodError, match="open-ended"):
        validate_new_status_period(existing_open, StatusPeriod("2026-09-01", None))


@pytest.mark.acceptance
def test_db_rejects_reversed_status_dates(tmp_path: Path) -> None:
    conn, ids = _db(tmp_path)
    emp = ids["employee_a_id"]
    created = "2026-08-01T12:00:00Z"

    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute(
            "INSERT INTO status_history ("
            " employee_id, status_id, start_date, end_date, created_at"
            ") VALUES (?, 1, '2026-08-10', '2026-08-01', ?)",
            (emp, created),
        )
    conn.close()


@pytest.mark.acceptance
def test_status_history_service_rejects_unconfirmed_overlap(tmp_path: Path) -> None:
    from services.bootstrap import BootstrapService
    from services.status_history import ConfirmationRequiredError, StatusHistoryService

    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-01T10:00:00Z")
    conn, session, _ = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    ids = seed_synthetic_org(conn)
    svc = StatusHistoryService(conn, session, clock=lambda: "2026-08-01T12:00:00Z")
    emp = ids["employee_a_id"]
    svc.assign_status(
        employee_id=emp,
        status_id=1,
        start_date="2026-08-01",
        end_date="2026-08-10",
    )
    with pytest.raises(ConfirmationRequiredError):
        svc.assign_status(
            employee_id=emp,
            status_id=2,
            start_date="2026-08-05",
            end_date="2026-08-12",
        )
    conn.close()
