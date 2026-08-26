"""Unit: пересечения и порядок дат статусов."""

import pytest

from domain.status_periods import StatusPeriod, StatusPeriodError, periods_overlap, validate_date_order


def test_periods_overlap_with_open_ended() -> None:
    assert periods_overlap(StatusPeriod("2026-01-01", "2026-01-10"), StatusPeriod("2026-01-10", "2026-01-20"))
    assert periods_overlap(StatusPeriod("2026-01-01", None), StatusPeriod("2026-06-01", "2026-06-02"))
    assert not periods_overlap(StatusPeriod("2026-01-01", "2026-01-10"), StatusPeriod("2026-01-11", None))


def test_validate_date_order() -> None:
    validate_date_order(StatusPeriod("2026-01-01", "2026-01-02"))
    with pytest.raises(StatusPeriodError):
        validate_date_order(StatusPeriod("2026-01-10", "2026-01-01"))
