"""Инварианты периодов статусов (ANCHOR_CORE §3 / ТЗ §3.2) — без UI."""

from __future__ import annotations

from dataclasses import dataclass


class StatusPeriodError(ValueError):
    """Нарушение правил периодов статуса."""


@dataclass(frozen=True)
class StatusPeriod:
    start_date: str
    end_date: str | None = None


def validate_date_order(period: StatusPeriod) -> None:
    if period.end_date is not None and period.start_date > period.end_date:
        raise StatusPeriodError("start_date must be <= end_date")


def periods_overlap(a: StatusPeriod, b: StatusPeriod) -> bool:
    """Пересечение закрытых/открытых интервалов по календарным датам ISO (YYYY-MM-DD)."""
    a_end = a.end_date or "9999-12-31"
    b_end = b.end_date or "9999-12-31"
    return a.start_date <= b_end and b.start_date <= a_end


def validate_no_overlap(existing: list[StatusPeriod], candidate: StatusPeriod) -> None:
    validate_date_order(candidate)
    for period in existing:
        if periods_overlap(period, candidate):
            raise StatusPeriodError("overlapping status period for employee")


def validate_single_open_ended(existing: list[StatusPeriod], candidate: StatusPeriod) -> None:
    validate_date_order(candidate)
    if candidate.end_date is not None:
        return
    if any(p.end_date is None for p in existing):
        raise StatusPeriodError("duplicate open-ended status for employee")


def validate_new_status_period(existing: list[StatusPeriod], candidate: StatusPeriod) -> None:
    """Полная проверка перед добавлением записи истории статусов."""
    validate_date_order(candidate)
    validate_single_open_ended(existing, candidate)
    validate_no_overlap(existing, candidate)
