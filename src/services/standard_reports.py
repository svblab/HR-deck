"""Стандартные отчёты: выборка через существующие сервисы (ТЗ §3.8.1)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from data.db import Connection
from domain.employee import EmployeeCard
from domain.permissions import Permission
from domain.reports import (
    ABSENCE_STATUS_CODES,
    ABSENTEE_COLUMNS,
    CLARIFICATION_COLUMNS,
    HISTORY_COLUMNS,
    SNAPSHOT_COLUMNS,
    TEMPORARY_COLUMNS,
    TEMPORARY_EMPLOYMENT_CODE,
    ReportGroupBy,
    ReportKind,
    ReportParams,
    ReportRow,
    ReportTable,
    spec_for,
)
from domain.roster import RosterRow, format_display_date
from domain.status_periods import StatusPeriod, periods_overlap
from services.authorization import AuthorizationService
from services.availability_statuses import AvailabilityStatusService
from services.directories import DirectoryService
from services.employees import EmployeeService
from services.roster import RosterService
from services.session import SessionState
from services.status_clarification import StatusClarificationService
from services.status_history import StatusHistoryService

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class StandardReportService:
    """Read-only выборка. Не пишет в журнал (ТЗ §4.6 — отчёты не в скоупе аудита)."""

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
        self._employees = EmployeeService(conn, session, authz=self._authz, clock=self._clock)
        self._directories = DirectoryService(conn, session, authz=self._authz, clock=self._clock)
        self._history = StatusHistoryService(conn, session, authz=self._authz, clock=self._clock)
        self._clarify = StatusClarificationService(
            conn, session, authz=self._authz, clock=self._clock
        )
        self._statuses = AvailabilityStatusService(
            conn, session, authz=self._authz, clock=self._clock
        )

    def build(self, kind: ReportKind, params: ReportParams) -> ReportTable:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.VIEW_STANDARD_REPORTS)
        builders = {
            ReportKind.SNAPSHOT: self._snapshot,
            ReportKind.ABSENTEES: self._absentees,
            ReportKind.TEMPORARY: self._temporary,
            ReportKind.HISTORY: self._history_report,
            ReportKind.CLARIFICATION: self._clarification,
        }
        return builders[kind](params)

    def status_options(self) -> list[tuple[int, str]]:
        return [(s.id, s.name) for s in self._statuses.list_statuses(active_only=True)]

    def _cards(self) -> dict[int, EmployeeCard]:
        return {c.id: c for c in self._employees.list_employees(active_only=True)}

    def _employment_types(self) -> dict[int, str]:
        return {t.id: t.code for t in self._directories.list_employment_types(active_only=False)}

    def _pass_org(self, row: RosterRow, params: ReportParams) -> bool:
        if params.branch_id is not None and row.branch_id != params.branch_id:
            return False
        if params.department_id is not None and row.department_id != params.department_id:
            return False
        if params.division_id is not None and row.division_id != params.division_id:
            return False
        return True

    def _pass_status_emp(
        self,
        row: RosterRow,
        params: ReportParams,
        cards: dict[int, EmployeeCard],
    ) -> bool:
        if params.status_id is not None and row.status_id != params.status_id:
            return False
        if params.employment_type_id is not None:
            card = cards.get(row.employee_id)
            if card is None or card.employment_type_id != params.employment_type_id:
                return False
        return True

    def _group_label(self, row: RosterRow, params: ReportParams) -> str:
        if params.group_by == ReportGroupBy.DEPARTMENT:
            return row.department_name
        return row.branch_name

    def _snapshot(self, params: ReportParams) -> ReportTable:
        as_of = params.date_to or self._clock()[:10]
        cards = self._cards()
        rows = [
            r
            for r in self._roster.list_rows(as_of=as_of)
            if self._pass_org(r, params) and self._pass_status_emp(r, params, cards)
        ]
        rows.sort(key=lambda r: (self._group_label(r, params), r.full_name, r.employee_id))
        body = tuple(
            ReportRow(
                cells=(
                    r.full_name,
                    r.position_name,
                    r.status_name or "Требует уточнения",
                    format_display_date(r.start_date),
                    format_display_date(r.end_date),
                ),
                group_label=self._group_label(r, params),
            )
            for r in rows
        )
        return ReportTable(spec_for(ReportKind.SNAPSHOT).title, SNAPSHOT_COLUMNS, body)

    def _absentees(self, params: ReportParams) -> ReportTable:
        date_from = params.date_from or self._clock()[:10]
        date_to = params.date_to or date_from
        if date_from > date_to:
            return ReportTable(spec_for(ReportKind.ABSENTEES).title, ABSENTEE_COLUMNS, ())
        cards = self._cards()
        codes = self._status_codes()
        window = StatusPeriod(start_date=date_from, end_date=date_to)
        body: list[ReportRow] = []
        for row in self._roster.list_rows(as_of=date_to):
            if not self._pass_org(row, params):
                continue
            if not self._pass_status_emp(
                row,
                ReportParams(
                    employment_type_id=params.employment_type_id,
                    status_id=None,
                ),
                cards,
            ):
                continue
            for entry in self._history.list_history(row.employee_id):
                if not periods_overlap(
                    StatusPeriod(entry.start_date, entry.end_date), window
                ):
                    continue
                code = codes.get(entry.status_id, "")
                if code not in ABSENCE_STATUS_CODES:
                    continue
                if params.status_id is not None and entry.status_id != params.status_id:
                    continue
                name = row.status_name if entry.status_id == row.status_id else code
                status = self._status_name(entry.status_id) or name or ""
                body.append(
                    ReportRow(
                        cells=(
                            row.full_name,
                            row.position_name,
                            status,
                            format_display_date(entry.start_date),
                            format_display_date(entry.end_date),
                        )
                    )
                )
        body.sort(key=lambda r: (r.cells[0], r.cells[3]))
        return ReportTable(spec_for(ReportKind.ABSENTEES).title, ABSENTEE_COLUMNS, tuple(body))

    def _temporary(self, params: ReportParams) -> ReportTable:
        cards = self._cards()
        types = self._employment_types()
        temp_ids = {eid for eid, code in types.items() if code == TEMPORARY_EMPLOYMENT_CODE}
        as_of = params.date_to or self._clock()[:10]
        rows = []
        for row in self._roster.list_rows(as_of=as_of):
            card = cards.get(row.employee_id)
            if card is None or card.employment_type_id not in temp_ids:
                continue
            if not self._pass_org(row, params):
                continue
            if params.status_id is not None and row.status_id != params.status_id:
                continue
            rows.append(row)
        rows.sort(key=lambda r: (r.full_name, r.employee_id))
        body = tuple(
            ReportRow(
                cells=(
                    r.full_name,
                    r.position_name,
                    r.branch_name,
                    r.status_name or "Требует уточнения",
                )
            )
            for r in rows
        )
        return ReportTable(spec_for(ReportKind.TEMPORARY).title, TEMPORARY_COLUMNS, body)

    def _history_report(self, params: ReportParams) -> ReportTable:
        title = spec_for(ReportKind.HISTORY).title
        if params.employee_id is None:
            return ReportTable(title, HISTORY_COLUMNS, ())
        name = next(
            (c.full_name for c in self._employees.list_employees(active_only=False)
             if c.id == params.employee_id),
            f"#{params.employee_id}",
        )
        entries = self._history.list_history(params.employee_id)
        date_from = params.date_from
        date_to = params.date_to
        body: list[ReportRow] = []
        for entry in entries:
            if date_from and (entry.end_date or "9999-12-31") < date_from:
                continue
            if date_to and entry.start_date > date_to:
                continue
            body.append(
                ReportRow(
                    cells=(
                        self._status_name(entry.status_id) or str(entry.status_id),
                        format_display_date(entry.start_date),
                        format_display_date(entry.end_date),
                    )
                )
            )
        return ReportTable(f"{title}: {name}", HISTORY_COLUMNS, tuple(body))

    def _clarification(self, params: ReportParams) -> ReportTable:
        cards = self._cards()
        as_of = params.date_to or self._clock()[:10]
        roster = {
            r.employee_id: r for r in self._roster.list_rows(as_of=as_of)
        }
        hits = self._clarify.list_needing_clarification(as_of=as_of)
        body: list[ReportRow] = []
        for hit in hits:
            row = roster.get(hit.employee_id)
            if row is None:
                continue
            if not self._pass_org(row, params):
                continue
            if not self._pass_status_emp(
                row,
                ReportParams(employment_type_id=params.employment_type_id),
                cards,
            ):
                continue
            body.append(
                ReportRow(
                    cells=(
                        hit.full_name,
                        hit.last_status_name or "—",
                        format_display_date(hit.last_status_end_date),
                    ),
                    group_label=self._group_label(row, params),
                )
            )
        body.sort(key=lambda r: (r.group_label, r.cells[0]))
        return ReportTable(
            spec_for(ReportKind.CLARIFICATION).title, CLARIFICATION_COLUMNS, tuple(body)
        )

    def _status_codes(self) -> dict[int, str]:
        return {s.id: s.code for s in self._statuses.list_statuses(active_only=False)}

    def _status_name(self, status_id: int) -> str | None:
        for status in self._statuses.list_statuses(active_only=False):
            if status.id == status_id:
                return status.name
        return None
