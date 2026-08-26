"""Планирование назначения статусов: автозакрытие, задним числом, пересечения (ТЗ §3.2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from domain.status_periods import (
    StatusPeriod,
    StatusPeriodError,
    periods_overlap,
    validate_date_order,
)


@dataclass(frozen=True)
class StatusHistoryEntry:
    id: int
    status_id: int
    start_date: str
    end_date: str | None


@dataclass(frozen=True)
class StatusCorrectionProposal:
    status_history_id: int
    field_name: str
    old_value: str | None
    new_value: str | None
    reason: str


@dataclass(frozen=True)
class NewStatusPeriodProposal:
    status_id: int
    start_date: str
    end_date: str | None
    note: str | None = None


@dataclass(frozen=True)
class StatusAssignmentPlan:
    inserts: tuple[NewStatusPeriodProposal, ...]
    corrections: tuple[StatusCorrectionProposal, ...]
    requires_confirmation: bool


def day_before(iso_date: str) -> str:
    return (date.fromisoformat(iso_date) - timedelta(days=1)).isoformat()


def day_after(iso_date: str) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=1)).isoformat()


def apply_correction(
    entry: StatusHistoryEntry,
    correction: StatusCorrectionProposal,
) -> StatusHistoryEntry:
    if correction.status_history_id != entry.id:
        return entry
    start = entry.start_date
    end = entry.end_date
    if correction.field_name == "start_date":
        start = correction.new_value or start
    elif correction.field_name == "end_date":
        end = correction.new_value
    return StatusHistoryEntry(entry.id, entry.status_id, start, end)


def build_effective_timeline(
    rows: list[StatusHistoryEntry],
    corrections: list[StatusCorrectionProposal],
) -> list[StatusHistoryEntry]:
    by_id = {row.id: row for row in rows}
    for corr in corrections:
        row = by_id.get(corr.status_history_id)
        if row is not None:
            by_id[corr.status_history_id] = apply_correction(row, corr)
    effective = list(by_id.values())
    effective.sort(key=lambda r: (r.start_date, r.id))
    for entry in effective:
        validate_date_order(StatusPeriod(entry.start_date, entry.end_date))
    return effective


def _find_auto_close(
    effective: list[StatusHistoryEntry],
    new_start: str,
) -> StatusCorrectionProposal | None:
    for row in effective:
        if row.end_date is not None or row.start_date >= new_start:
            continue
        close_at = day_before(new_start)
        if close_at < row.start_date:
            continue
        return StatusCorrectionProposal(
            status_history_id=row.id,
            field_name="end_date",
            old_value=None,
            new_value=close_at,
            reason="auto_close",
        )
    return None


def _propose_row_adjustments(
    row: StatusHistoryEntry,
    candidate: StatusPeriod,
) -> tuple[list[StatusCorrectionProposal], list[NewStatusPeriodProposal]]:
    corrections: list[StatusCorrectionProposal] = []
    continuations: list[NewStatusPeriodProposal] = []

    if not periods_overlap(StatusPeriod(row.start_date, row.end_date), candidate):
        return corrections, continuations

    c_start = candidate.start_date
    c_end = candidate.end_date
    r_start = row.start_date
    r_end = row.end_date

    if c_end is None:
        raise StatusPeriodError("open-ended insert overlaps existing period")

    if c_start > r_start:
        corrections.append(
            StatusCorrectionProposal(
                status_history_id=row.id,
                field_name="end_date",
                old_value=r_end,
                new_value=day_before(c_start),
                reason="truncate_end_for_insert",
            )
        )

    tail_start = day_after(c_end)
    has_tail = r_end is None or tail_start <= r_end
    if has_tail and (r_end is None or c_end < r_end):
        if c_start > r_start:
            continuations.append(
                NewStatusPeriodProposal(
                    status_id=row.status_id,
                    start_date=tail_start,
                    end_date=r_end,
                )
            )
        else:
            corrections.append(
                StatusCorrectionProposal(
                    status_history_id=row.id,
                    field_name="start_date",
                    old_value=r_start,
                    new_value=tail_start,
                    reason="truncate_start_for_insert",
                )
            )

    return corrections, continuations


def _dedupe_corrections(
    corrections: list[StatusCorrectionProposal],
) -> tuple[StatusCorrectionProposal, ...]:
    merged: dict[tuple[int, str], StatusCorrectionProposal] = {}
    for corr in corrections:
        key = (corr.status_history_id, corr.field_name)
        if key in merged:
            prev = merged[key]
            merged[key] = StatusCorrectionProposal(
                status_history_id=corr.status_history_id,
                field_name=corr.field_name,
                old_value=prev.old_value,
                new_value=corr.new_value,
                reason=corr.reason,
            )
        else:
            merged[key] = corr
    return tuple(merged.values())


def _validate_final_timeline(
    existing: list[StatusHistoryEntry],
    plan: StatusAssignmentPlan,
) -> None:
    effective = build_effective_timeline(existing, list(plan.corrections))
    candidate_periods = [
        StatusPeriod(p.start_date, p.end_date) for p in plan.inserts
    ]
    for period in candidate_periods:
        validate_date_order(period)
        for row in effective:
            if periods_overlap(StatusPeriod(row.start_date, row.end_date), period):
                raise StatusPeriodError("plan leaves overlapping periods")
    for i, a in enumerate(candidate_periods):
        for b in candidate_periods[i + 1 :]:
            if periods_overlap(a, b):
                raise StatusPeriodError("plan inserts overlap each other")


def plan_status_assignment(
    existing: list[StatusHistoryEntry],
    *,
    status_id: int,
    start_date: str,
    end_date: str | None = None,
    note: str | None = None,
) -> StatusAssignmentPlan:
    """Сформировать план: автозакрытие без подтверждения; пересечения — с подтверждением."""
    validate_date_order(StatusPeriod(start_date, end_date))

    corrections: list[StatusCorrectionProposal] = []
    continuations: list[NewStatusPeriodProposal] = []
    requires_confirmation = False

    effective = build_effective_timeline(existing, corrections)
    auto_close = _find_auto_close(effective, start_date)
    if auto_close is not None:
        corrections.append(auto_close)
        effective = build_effective_timeline(existing, corrections)

    candidate = StatusPeriod(start_date, end_date)
    for row in effective:
        if not periods_overlap(StatusPeriod(row.start_date, row.end_date), candidate):
            continue
        if auto_close is not None and row.id == auto_close.status_history_id:
            continue
        requires_confirmation = True
        row_corrections, row_continuations = _propose_row_adjustments(row, candidate)
        corrections.extend(row_corrections)
        continuations.extend(row_continuations)

    deduped = _dedupe_corrections(corrections)
    inserts = (
        NewStatusPeriodProposal(status_id, start_date, end_date, note),
        *continuations,
    )
    plan = StatusAssignmentPlan(
        inserts=inserts,
        corrections=deduped,
        requires_confirmation=requires_confirmation,
    )
    _validate_final_timeline(existing, plan)
    return plan


def current_status_at(
    rows: list[StatusHistoryEntry],
    corrections: list[StatusCorrectionProposal],
    as_of: str,
) -> StatusHistoryEntry | None:
    """Статус, действующий на дату as_of (YYYY-MM-DD); будущие периоды не «текущие»."""
    effective = build_effective_timeline(rows, corrections)
    for row in reversed(effective):
        if row.start_date > as_of:
            continue
        if row.end_date is not None and row.end_date < as_of:
            continue
        return row
    return None
