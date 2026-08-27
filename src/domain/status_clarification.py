"""Определение «Требует уточнения статуса» (ТЗ §3.3 / ANCHOR_CORE §3)."""

from __future__ import annotations

from dataclasses import dataclass

from domain.status_assignment import (
    StatusCorrectionProposal,
    StatusHistoryEntry,
    build_effective_timeline,
    current_status_at,
)


@dataclass(frozen=True)
class LastStatusSnapshot:
    status_id: int | None
    end_date: str | None


def last_status_period(
    rows: list[StatusHistoryEntry],
    corrections: list[StatusCorrectionProposal],
) -> StatusHistoryEntry | None:
    """Последний период по дате начала (для отображения в списке уточнений)."""
    effective = build_effective_timeline(rows, corrections)
    if not effective:
        return None
    return max(effective, key=lambda r: (r.start_date, r.id))


def needs_status_clarification(
    rows: list[StatusHistoryEntry],
    corrections: list[StatusCorrectionProposal],
    *,
    as_of: str,
) -> bool:
    """
    True, если на дату as_of нет действующего статуса.

    Покрывает: истёкший период без следующего, отсутствие истории,
    только плановые будущие периоды (не «текущие» до наступления даты).
    """
    if current_status_at(rows, corrections, as_of) is not None:
        return False
    return True


def last_status_snapshot(
    rows: list[StatusHistoryEntry],
    corrections: list[StatusCorrectionProposal],
) -> LastStatusSnapshot:
    period = last_status_period(rows, corrections)
    if period is None:
        return LastStatusSnapshot(status_id=None, end_date=None)
    return LastStatusSnapshot(status_id=period.status_id, end_date=period.end_date)
