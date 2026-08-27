"""Unit: определение «Требует уточнения статуса» (ТЗ §3.3)."""

from __future__ import annotations

from domain.status_assignment import StatusHistoryEntry
from domain.status_clarification import (
    last_status_period,
    needs_status_clarification,
)


def test_open_period_does_not_need_clarification() -> None:
    rows = [StatusHistoryEntry(1, 2, "2026-08-01", None)]
    assert needs_status_clarification(rows, [], as_of="2026-08-15") is False


def test_expired_period_needs_clarification() -> None:
    rows = [StatusHistoryEntry(1, 1, "2026-08-01", "2026-08-10")]
    assert needs_status_clarification(rows, [], as_of="2026-08-11") is True


def test_no_history_needs_clarification() -> None:
    assert needs_status_clarification([], [], as_of="2026-08-01") is True


def test_future_only_period_needs_clarification_today() -> None:
    rows = [StatusHistoryEntry(1, 5, "2026-09-01", "2026-09-14")]
    assert needs_status_clarification(rows, [], as_of="2026-08-15") is True


def test_last_status_period_picks_latest_start() -> None:
    rows = [
        StatusHistoryEntry(1, 1, "2026-01-01", "2026-01-31"),
        StatusHistoryEntry(2, 2, "2026-02-01", "2026-02-28"),
    ]
    last = last_status_period(rows, [])
    assert last is not None
    assert last.status_id == 2
