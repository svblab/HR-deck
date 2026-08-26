"""StatusHistoryService: запись через сервис с RBAC (EPIC-006)."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.bootstrap import BootstrapService
from services.status_history import StatusHistoryService
from tests.fixtures.synthetic import seed_synthetic_org


@pytest.mark.acceptance
def test_status_history_service_assign_persists_row(tmp_path: Path) -> None:
    bootstrap = BootstrapService(clock=lambda: "2026-08-01T12:00:00Z")
    conn, session, _ = bootstrap.initial_administrator_setup(
        db_path=tmp_path / "app.db",
        login="admin",
        password="AdminPass-1",
    )
    ids = seed_synthetic_org(conn)

    svc = StatusHistoryService(conn, session, clock=lambda: "2026-08-01T12:00:00Z")
    row_id = svc.assign_status(
        employee_id=ids["employee_a_id"],
        status_id=1,
        start_date="2026-08-01",
        end_date="2026-08-15",
        note="service-write",
    )

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
    assert len(svc.list_history(ids["employee_a_id"])) == 1
    conn.close()
