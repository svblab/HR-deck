"""Unit: планирование назначения статусов (ТЗ §3.2 / ANCHOR_CORE §3)."""

from __future__ import annotations

from domain.status_assignment import (
    StatusHistoryEntry,
    current_status_at,
    day_before,
    plan_status_assignment,
)


def test_auto_close_open_period_before_new_start() -> None:
    existing = [StatusHistoryEntry(1, 2, "2026-01-01", None)]
    plan = plan_status_assignment(
        existing,
        status_id=1,
        start_date="2026-02-01",
    )
    assert plan.requires_confirmation is False
    assert len(plan.corrections) == 1
    assert plan.corrections[0].reason == "auto_close"
    assert plan.corrections[0].new_value == day_before("2026-02-01")
    assert plan.inserts[0].start_date == "2026-02-01"


def test_future_period_does_not_become_current() -> None:
    existing = [StatusHistoryEntry(1, 2, "2026-01-01", None)]
    plan = plan_status_assignment(
        existing,
        status_id=5,
        start_date="2026-09-01",
        end_date="2026-09-14",
    )
    assert plan.requires_confirmation is False
    assert current_status_at(existing, list(plan.corrections), "2026-08-01") is not None
    assert current_status_at(existing, list(plan.corrections), "2026-08-01").status_id == 2
    future = current_status_at(
        existing + [StatusHistoryEntry(99, 5, "2026-09-01", "2026-09-14")],
        list(plan.corrections),
        "2026-08-15",
    )
    assert future is None or future.status_id == 2


def test_backdate_into_closed_period_requires_confirmation() -> None:
    existing = [StatusHistoryEntry(1, 1, "2026-01-01", "2026-01-31")]
    plan = plan_status_assignment(
        existing,
        status_id=4,
        start_date="2026-01-15",
        end_date="2026-01-20",
    )
    assert plan.requires_confirmation is True
    assert plan.inserts[0].status_id == 4
    assert any(c.reason == "truncate_end_for_insert" for c in plan.corrections)
    assert len(plan.inserts) == 2  # sick leave + office tail


def test_non_overlapping_append_no_confirmation() -> None:
    existing = [StatusHistoryEntry(1, 1, "2026-01-01", "2026-01-31")]
    plan = plan_status_assignment(
        existing,
        status_id=2,
        start_date="2026-02-01",
    )
    assert plan.requires_confirmation is False
    assert plan.corrections == ()


def test_overlap_plan_requires_confirmation() -> None:
    existing = [StatusHistoryEntry(1, 1, "2026-01-01", "2026-01-31")]
    plan = plan_status_assignment(
        existing,
        status_id=2,
        start_date="2026-01-10",
        end_date="2026-02-05",
    )
    assert plan.requires_confirmation is True
