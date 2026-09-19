"""Подготовка данных для Excel-шаблона «Сводка по филиалу на текущую дату»."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from data.db import Connection
from domain.branch_summary import build_branch_summary_context
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.availability_statuses import AvailabilityStatusService
from services.roster import RosterService
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class BranchSummaryReportService:
    """Агрегация roster → scalars + row_records для шаблонов Excel."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._session = session
        self._authz = authz or AuthorizationService()
        self._clock: Clock = clock or _utc_now
        self._roster = RosterService(conn, session, authz=self._authz, clock=self._clock)
        self._statuses = AvailabilityStatusService(
            conn, session, authz=self._authz, clock=self._clock
        )

    def build_context(
        self,
        branch_id: int,
        *,
        as_of: str | None = None,
        title: str = "Сводка по филиалу",
    ) -> tuple[dict[str, str], list[dict[str, str]]]:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.VIEW_STANDARD_REPORTS)
        as_of_date = as_of or self._clock()[:10]
        rows = [
            row
            for row in self._roster.list_rows(as_of=as_of_date)
            if row.branch_id == branch_id
        ]
        branch_name = rows[0].branch_name if rows else ""
        codes = {status.id: status.code for status in self._statuses.list_statuses(active_only=False)}
        return build_branch_summary_context(
            rows,
            codes,
            branch_name=branch_name,
            as_of=as_of_date,
            title=title,
        )
