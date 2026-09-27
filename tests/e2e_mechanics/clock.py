"""Controllable UTC clock shared by both peers (reproducible clarification dates)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class ScenarioClock:
    """Mutable clock injectable into Bootstrap / services."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        self._now = start.astimezone(UTC).replace(microsecond=0)

    def __call__(self) -> str:
        return self._now.isoformat().replace("+00:00", "Z")

    @property
    def date(self) -> str:
        return self._now.date().isoformat()

    def advance(self, *, days: int = 0, hours: int = 0, minutes: int = 0) -> None:
        self._now += timedelta(days=days, hours=hours, minutes=minutes)

    def set(self, when: datetime) -> None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        self._now = when.astimezone(UTC).replace(microsecond=0)
