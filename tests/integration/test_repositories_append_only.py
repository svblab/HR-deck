"""Append-only: Python API и DB triggers (TESTING §2.2 / ANCHOR_CORE A9)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from data.repositories import (
    AppendOnlyViolation,
    StatusHistoryRepository,
    TechnicalEventRepository,
    UserActionLogRepository,
)
from tests.fixtures.synthetic import seed_synthetic_org


def _migrated(tmp_path: Path):
    key = generate_master_key()
    path = tmp_path / "app.db"
    conn = create_database(path, key)
    apply_pending_migrations(conn)
    ids = seed_synthetic_org(conn)
    return conn, ids


@pytest.mark.acceptance
def test_repository_api_rejects_update_delete(tmp_path: Path) -> None:
    conn, ids = _migrated(tmp_path)
    history = StatusHistoryRepository(conn)
    history.add(
        employee_id=ids["employee_a_id"],
        status_id=1,
        start_date="2026-08-01",
        created_at="2026-08-01T12:00:00Z",
    )
    with pytest.raises(AppendOnlyViolation):
        history.update(1, {"note": "x"})
    with pytest.raises(AppendOnlyViolation):
        history.delete(1)

    actions = UserActionLogRepository(conn)
    actions.record(
        action_type="test",
        result="success",
        created_at="2026-08-01T12:00:00Z",
        entity_type="employee",
        entity_id=ids["employee_a_id"],
    )
    with pytest.raises(AppendOnlyViolation):
        actions.update(1)
    with pytest.raises(AppendOnlyViolation):
        actions.delete(1)

    tech = TechnicalEventRepository(conn)
    tech.record(event_type="startup", message="test start", created_at="2026-08-01T12:00:00Z")
    with pytest.raises(AppendOnlyViolation):
        tech.update(1)
    with pytest.raises(AppendOnlyViolation):
        tech.delete(1)
    conn.close()


@pytest.mark.acceptance
def test_db_triggers_reject_direct_sql_on_status_history(tmp_path: Path) -> None:
    conn, ids = _migrated(tmp_path)
    created = "2026-08-01T12:00:00Z"
    conn.execute(
        "INSERT INTO status_history ("
        " employee_id, status_id, start_date, end_date, note, created_at,"
        " created_by_account_id) VALUES (?, 1, '2026-08-01', NULL, NULL, ?, NULL)",
        (ids["employee_a_id"], created),
    )
    conn.commit()
    row_id = conn.execute("SELECT id FROM status_history LIMIT 1").fetchone()[0]
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute("UPDATE status_history SET note = ? WHERE id = ?", ("x", row_id))
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute("DELETE FROM status_history WHERE id = ?", (row_id,))
    assert conn.execute(
        "SELECT COUNT(*) FROM status_history WHERE id = ?", (row_id,)
    ).fetchone()[0] == 1
    conn.close()


@pytest.mark.acceptance
def test_db_triggers_reject_direct_sql_on_user_action_log(tmp_path: Path) -> None:
    conn, ids = _migrated(tmp_path)
    created = "2026-08-01T12:00:00Z"
    conn.execute(
        "INSERT INTO user_action_log ("
        " account_id, action_type, entity_type, entity_id, result, details, created_at"
        ") VALUES (NULL, 't', 'employee', ?, 'ok', NULL, ?)",
        (ids["employee_a_id"], created),
    )
    conn.commit()
    row_id = conn.execute("SELECT id FROM user_action_log LIMIT 1").fetchone()[0]
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute("UPDATE user_action_log SET result = ? WHERE id = ?", ("fail", row_id))
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute("DELETE FROM user_action_log WHERE id = ?", (row_id,))
    conn.close()


@pytest.mark.acceptance
def test_db_triggers_reject_direct_sql_on_technical_events(tmp_path: Path) -> None:
    conn, _ids = _migrated(tmp_path)
    created = "2026-08-01T12:00:00Z"
    conn.execute(
        "INSERT INTO technical_events (event_type, message, created_at) VALUES ('t', 'm', ?)",
        (created,),
    )
    conn.commit()
    row_id = conn.execute("SELECT id FROM technical_events LIMIT 1").fetchone()[0]
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute("UPDATE technical_events SET message = ? WHERE id = ?", ("x", row_id))
    with pytest.raises(sqlcipher.DatabaseError):
        conn.execute("DELETE FROM technical_events WHERE id = ?", (row_id,))
    conn.close()
