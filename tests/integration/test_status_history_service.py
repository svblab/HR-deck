"""StatusHistoryService: реальная запись через typed repository (P0-3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import create_database, generate_master_key
from data.migrations import apply_pending_migrations
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org


@pytest.mark.acceptance
def test_status_history_service_add_period_persists_row(tmp_path: Path) -> None:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    ids = seed_synthetic_org(conn)

    svc = StatusHistoryService(conn)
    row_id = svc.add_period(
        employee_id=ids["employee_a_id"],
        status_id=1,
        start_date="2026-08-01",
        end_date="2026-08-15",
        created_at="2026-08-01T12:00:00Z",
        note="service-write",
    )
    conn.commit()

    assert row_id > 0
    row = conn.execute(
        "SELECT employee_id, status_id, start_date, end_date, note "
        "FROM status_history WHERE id = ?",
        (row_id,),
    ).fetchone()
    assert row == (
        ids["employee_a_id"],
        1,
        "2026-08-01",
        "2026-08-15",
        "service-write",
    )
    assert len(svc.list_periods(ids["employee_a_id"])) == 1
    conn.close()
