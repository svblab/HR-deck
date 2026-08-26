"""Append-only API журналов (TESTING §2.2 / ANCHOR_CORE A9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from data.repositories import (
    AppendOnlyViolation,
    StatusHistoryRepository,
    TechnicalEventRepository,
    UserActionLogRepository,
)
from tests.fixtures.synthetic import seed_synthetic_org


@pytest.mark.acceptance
def test_status_history_and_action_log_reject_update_delete(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn)
    ids = seed_synthetic_org(conn)

    history = StatusHistoryRepository(conn)
    history.insert(
        {
            "employee_id": ids["employee_a_id"],
            "status_id": 1,
            "start_date": "2026-08-01",
            "end_date": None,
            "note": None,
            "created_at": "2026-08-01T12:00:00Z",
            "created_by_account_id": None,
        }
    )
    with pytest.raises(AppendOnlyViolation):
        history.update(1, {"note": "x"})
    with pytest.raises(AppendOnlyViolation):
        history.delete(1)

    actions = UserActionLogRepository(conn)
    actions.insert(
        {
            "account_id": None,
            "action_type": "test",
            "entity_type": "employee",
            "entity_id": ids["employee_a_id"],
            "result": "success",
            "details": None,
            "created_at": "2026-08-01T12:00:00Z",
        }
    )
    with pytest.raises(AppendOnlyViolation):
        actions.update(1)
    with pytest.raises(AppendOnlyViolation):
        actions.delete(1)

    tech = TechnicalEventRepository(conn)
    tech.insert("startup", "test start", "2026-08-01T12:00:00Z")
    with pytest.raises(AppendOnlyViolation):
        tech.update(1)
    with pytest.raises(AppendOnlyViolation):
        tech.delete(1)

    conn.close()
