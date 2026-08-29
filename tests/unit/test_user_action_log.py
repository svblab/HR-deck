"""Unit: фильтры журнала действий и RBAC просмотра (ТЗ §4.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from data.repositories import UserActionLogRepository
from domain.action_log import ENTITY_TEMPLATE, ActionLogFilters
from domain.permissions import RoleCode
from services.authorization import AuthorizationError
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.user_action_log import UserActionLogService


def _repo(tmp_path: Path) -> tuple[UserActionLogRepository, object]:
    conn = create_database(tmp_path / "log.db", generate_master_key())
    apply_pending_migrations(conn)
    repo = UserActionLogRepository(conn)
    repo.record(
        action_type="employee.create",
        result="success",
        created_at="2026-08-01T10:00:00Z",
        entity_type="employee",
        entity_id=1,
    )
    repo.record(
        action_type="employee.update",
        result="success",
        created_at="2026-08-02T10:00:00Z",
        entity_type="employee",
        entity_id=2,
    )
    repo.record(
        action_type="account.reset_password",
        result="success",
        created_at="2026-08-03T10:00:00Z",
        entity_type="account",
        entity_id=5,
    )
    repo.record(
        action_type="template.save",
        result="success",
        created_at="2026-08-04T10:00:00Z",
        entity_type=ENTITY_TEMPLATE,
        entity_id=9,
    )
    conn.commit()
    return repo, conn


@pytest.mark.acceptance
def test_list_entries_no_filters_returns_all(tmp_path: Path) -> None:
    repo, conn = _repo(tmp_path)
    rows = repo.list_entries()
    assert [r.action_type for r in rows] == [
        "template.save",
        "account.reset_password",
        "employee.update",
        "employee.create",
    ]
    conn.close()


def test_list_entries_single_filters(tmp_path: Path) -> None:
    repo, conn = _repo(tmp_path)
    by_type = repo.list_entries(action_type="employee.create")
    assert [r.entity_id for r in by_type] == [1]
    by_entity = repo.list_entries(entity_type="employee")
    assert {r.action_type for r in by_entity} == {"employee.create", "employee.update"}
    by_id = repo.list_entries(entity_type="employee", entity_id=2)
    assert [r.action_type for r in by_id] == ["employee.update"]
    later = repo.list_entries(created_from="2026-08-03")
    assert [r.action_type for r in later] == ["template.save", "account.reset_password"]
    until = repo.list_entries(created_to_exclusive="2026-08-03")
    assert [r.action_type for r in until] == ["employee.update", "employee.create"]
    conn.close()


def test_list_entries_combined_and_empty(tmp_path: Path) -> None:
    repo, conn = _repo(tmp_path)
    combined = repo.list_entries(
        action_type="employee.update",
        entity_type="employee",
        created_from="2026-08-02",
        created_to_exclusive="2026-08-03",
    )
    assert len(combined) == 1
    assert combined[0].entity_id == 2
    assert repo.list_entries(action_type="does.not.exist") == []
    assert repo.list_template_refs() == [(9, "9")]
    conn.close()


def test_service_has_no_mutating_methods() -> None:
    names = {
        name
        for name in dir(UserActionLogService)
        if not name.startswith("_") and callable(getattr(UserActionLogService, name, None))
    }
    assert names.isdisjoint({"record", "update", "delete", "insert", "create", "save", "write"})


def _admin(tmp_path: Path):
    conn, session, _code = BootstrapService(
        clock=lambda: "2026-08-26T12:00:00Z"
    ).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    return conn, session


def test_non_admin_cannot_list_or_export(tmp_path: Path) -> None:
    conn, admin = _admin(tmp_path)
    hr = SessionState(
        account_id=admin.account_id,
        login="hr1",
        role=RoleCode.HR_EMPLOYEE,
        master_key=admin.master_key,
    )
    denied = UserActionLogService(conn, hr)
    with pytest.raises(AuthorizationError):
        denied.list_entries()
    with pytest.raises(AuthorizationError):
        denied.export_xlsx(tmp_path / "x.xlsx")
    conn.close()


def test_service_date_range_is_inclusive(tmp_path: Path) -> None:
    conn, session = _admin(tmp_path)
    repo = UserActionLogRepository(conn)
    repo.record(
        action_type="extra",
        result="success",
        created_at="2026-08-27T00:00:00Z",
        account_id=session.account_id,
    )
    conn.commit()
    log = UserActionLogService(conn, session)
    rows = log.list_entries(
        ActionLogFilters(created_from="2026-08-26", created_to="2026-08-26")
    )
    assert rows
    assert all(r.created_at.startswith("2026-08-26") for r in rows)
    conn.close()


def test_employee_and_template_filters_are_exclusive(tmp_path: Path) -> None:
    conn, session = _admin(tmp_path)
    log = UserActionLogService(conn, session)
    assert log.list_entries(ActionLogFilters(employee_id=1, template_id=9)) == []
    conn.close()

