"""Сервис «Требует уточнения статуса»: обнаружение и списки (EPIC-007)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from data.availability_statuses import AvailabilityStatusRepository
from data.db import Connection
from data.employees import EmployeeRepository
from data.status_history import (
    StatusHistoryCorrectionRepository,
    StatusHistoryRepository,
)
from domain.permissions import Permission
from domain.status_assignment import StatusCorrectionProposal, StatusHistoryEntry
from domain.status_clarification import (
    last_status_snapshot,
    needs_status_clarification,
)
from services.authorization import AuthorizationError, AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ClarificationEmployeeHit:
    employee_id: int
    full_name: str
    last_status_id: int | None
    last_status_name: str | None
    last_status_end_date: str | None


@dataclass(frozen=True)
class ClarificationCounterSnapshot:
    """Снимок для напоминания при запуске и счётчика главного экрана (EPIC-008)."""

    count: int
    as_of_date: str


class StatusClarificationService:
    """Read-only обнаружение сотрудников без действующего статуса на «сегодня»."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._authz = authz or AuthorizationService()
        self._clock: Clock = clock or _utc_now
        self._employees = EmployeeRepository(conn)
        self._history = StatusHistoryRepository(conn)
        self._corrections = StatusHistoryCorrectionRepository(conn)
        self._statuses = AvailabilityStatusRepository(conn)
        self._cached_count: ClarificationCounterSnapshot | None = None

    def startup_clarification_count(self) -> ClarificationCounterSnapshot:
        """API при запуске приложения: «Требуют уточнения: N»."""
        self._require_view()
        as_of = self._clock()[:10]
        count = self.count_needing_clarification(as_of=as_of)
        snapshot = ClarificationCounterSnapshot(count=count, as_of_date=as_of)
        self._cached_count = snapshot
        return snapshot

    def persistent_counter_snapshot(self) -> ClarificationCounterSnapshot:
        """
        Placeholder для постоянного счётчика главного экрана (EPIC-008).

        Пересчитывает актуальное значение; UI может кэшировать и обновлять
        после мутаций статусов.
        """
        return self.startup_clarification_count()

    def count_needing_clarification(self, *, as_of: str | None = None) -> int:
        self._require_view()
        as_of_date = as_of or self._clock()[:10]
        return len(self._collect_hits(as_of_date))

    def list_needing_clarification(
        self,
        *,
        as_of: str | None = None,
    ) -> list[ClarificationEmployeeHit]:
        self._require_view()
        as_of_date = as_of or self._clock()[:10]
        hits = self._collect_hits(as_of_date)
        hits.sort(key=lambda h: (h.full_name, h.employee_id))
        return hits

    def employee_needs_clarification(
        self,
        employee_id: int,
        *,
        as_of: str | None = None,
    ) -> bool:
        self._require_view()
        employee = self._employees.get(employee_id)
        if employee is None or employee.is_archived:
            return False
        as_of_date = as_of or self._clock()[:10]
        rows, corrections = self._timeline(employee_id)
        return needs_status_clarification(rows, corrections, as_of=as_of_date)

    def filter_needing_clarification(
        self,
        employee_ids: list[int],
        *,
        as_of: str | None = None,
    ) -> list[int]:
        """Подмножество id для фильтра «только требующие уточнения» (EPIC-008)."""
        self._require_view()
        as_of_date = as_of or self._clock()[:10]
        needing = {h.employee_id for h in self._collect_hits(as_of_date)}
        return [eid for eid in employee_ids if eid in needing]

    def _collect_hits(self, as_of_date: str) -> list[ClarificationEmployeeHit]:
        hits: list[ClarificationEmployeeHit] = []
        for employee in self._employees.list(active_only=True):
            rows, corrections = self._timeline(employee.id)
            if not needs_status_clarification(rows, corrections, as_of=as_of_date):
                continue
            snapshot = last_status_snapshot(rows, corrections)
            status_name = None
            if snapshot.status_id is not None:
                status = self._statuses.get(snapshot.status_id)
                status_name = status.name if status else None
            hits.append(
                ClarificationEmployeeHit(
                    employee_id=employee.id,
                    full_name=employee.full_name,
                    last_status_id=snapshot.status_id,
                    last_status_name=status_name,
                    last_status_end_date=snapshot.end_date,
                )
            )
        return hits

    def _timeline(
        self,
        employee_id: int,
    ) -> tuple[list[StatusHistoryEntry], list[StatusCorrectionProposal]]:
        rows = [
            StatusHistoryEntry(
                id=r.id,
                status_id=r.status_id,
                start_date=r.start_date,
                end_date=r.end_date,
            )
            for r in self._history.list_for_employee(employee_id)
        ]
        corrections = [
            StatusCorrectionProposal(
                status_history_id=r.status_history_id,
                field_name=r.field_name,
                old_value=r.old_value,
                new_value=r.new_value,
                reason=r.reason,
            )
            for r in self._corrections.list_for_employee(employee_id)
        ]
        return rows, corrections

    def _require_view(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.VIEW_EMPLOYEES)
        self._authz.require(self._session.role, Permission.VIEW_STATUSES)


__all__ = [
    "AuthorizationError",
    "ClarificationCounterSnapshot",
    "ClarificationEmployeeHit",
    "StatusClarificationService",
]
