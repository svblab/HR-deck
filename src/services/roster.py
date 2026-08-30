"""Сборка строк главного экрана: сотрудники + текущий/последний статус (read-only)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from data.availability_statuses import AvailabilityStatusRepository
from data.db import Connection
from data.directories import (
    BranchRepository,
    DepartmentRepository,
    DivisionRepository,
    PositionRepository,
)
from data.employees import EmployeeRecord, EmployeeRepository
from data.status_history import StatusHistoryCorrectionRepository, StatusHistoryRepository
from domain.permissions import Permission
from domain.roster import (
    ColumnSpec,
    GroupBy,
    HistoryPreviewRow,
    RosterFilters,
    RosterRow,
    apply_filters,
)
from domain.status_assignment import StatusCorrectionProposal, StatusHistoryEntry, current_status_at
from domain.status_clarification import last_status_period, needs_status_clarification
from services.authorization import AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RosterService:
    """Проекция доски/таблицы. Не пишет в журнал — только чтение (ANCHOR_CORE §4)."""

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
        self._branches = BranchRepository(conn)
        self._departments = DepartmentRepository(conn)
        self._divisions = DivisionRepository(conn)
        self._positions = PositionRepository(conn)

    def list_rows(
        self,
        *,
        as_of: str | None = None,
        filters: RosterFilters | None = None,
        include_archived: bool = False,
    ) -> list[RosterRow]:
        self._require_view()
        as_of_date = as_of or self._clock()[:10]
        rows = [
            self._to_row(emp, as_of_date)
            for emp in self._employees.list(active_only=not include_archived)
        ]
        if filters is None:
            return rows
        return apply_filters(rows, filters)

    def column_specs(self, group_by: GroupBy) -> list[ColumnSpec]:
        self._require_view()
        if group_by == GroupBy.STATUS:
            return [
                ColumnSpec(key=s.id, title=s.name, color_hex=s.color_hex)
                for s in self._statuses.list(active_only=True)
            ]
        if group_by == GroupBy.BRANCH:
            return [
                ColumnSpec(key=b.id, title=b.name)
                for b in self._branches.list(active_only=True)
            ]
        return [
            ColumnSpec(key=d.id, title=d.name)
            for d in self._departments.list(active_only=True)
        ]

    def filter_branches(self):
        self._require_view()
        return self._branches.list(active_only=True)

    def filter_departments(self, *, branch_id: int | None = None):
        self._require_view()
        return self._departments.list(branch_id=branch_id, active_only=True)

    def filter_divisions(self, *, department_id: int | None = None):
        self._require_view()
        return self._divisions.list(department_id=department_id, active_only=True)

    def history_preview(self, employee_id: int, *, limit: int = 5) -> list[HistoryPreviewRow]:
        self._require_view()
        rows, _corrections = self._timeline(employee_id)
        rows.sort(key=lambda r: (r.start_date, r.id), reverse=True)
        previews: list[HistoryPreviewRow] = []
        for entry in rows[:limit]:
            status = self._statuses.get(entry.status_id)
            previews.append(
                HistoryPreviewRow(
                    start_date=entry.start_date,
                    end_date=entry.end_date,
                    status_name=status.name if status else f"#{entry.status_id}",
                )
            )
        return previews

    def _to_row(self, emp: EmployeeRecord, as_of_date: str) -> RosterRow:
        rows, corrections = self._timeline(emp.id)
        current = current_status_at(rows, corrections, as_of_date)
        needs = needs_status_clarification(rows, corrections, as_of=as_of_date)
        if current is not None:
            status_id = current.status_id
            start_date = current.start_date
            end_date = current.end_date
        else:
            period = last_status_period(rows, corrections)
            status_id = period.status_id if period else None
            start_date = period.start_date if period else None
            end_date = period.end_date if period else None

        status = self._statuses.get(status_id) if status_id is not None else None
        position = self._positions.get(emp.position_id)
        branch = self._branches.get(emp.branch_id)
        department = self._departments.get(emp.department_id)
        division = self._divisions.get(emp.division_id) if emp.division_id is not None else None
        return RosterRow(
            employee_id=emp.id,
            full_name=emp.full_name,
            position_name=position.name if position else "",
            branch_id=emp.branch_id,
            branch_name=branch.name if branch else "",
            department_id=emp.department_id,
            department_name=department.name if department else "",
            division_id=emp.division_id,
            division_name=division.name if division else None,
            status_id=status.id if status else None,
            status_name=status.name if status else None,
            status_color_hex=status.color_hex if status else None,
            start_date=start_date,
            end_date=end_date,
            needs_clarification=needs,
        )

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
        self._authz.require(self._session.role, Permission.VIEW_DIRECTORIES)
