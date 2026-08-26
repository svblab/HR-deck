"""Назначение периодов статусов: автозакрытие, плановые, задним числом (EPIC-006)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from data.availability_statuses import AvailabilityStatusRepository
from data.db import Connection
from data.employees import EmployeeRepository
from data.repositories import UserActionLogRepository
from data.status_history import (
    StatusHistoryCorrectionRepository,
    StatusHistoryRepository,
)
from domain.permissions import Permission
from domain.status_assignment import (
    StatusAssignmentPlan,
    StatusCorrectionProposal,
    StatusHistoryEntry,
    build_effective_timeline,
    current_status_at,
    plan_status_assignment,
)
from services.authorization import AuthorizationError, AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class StatusHistoryError(Exception):
    """Ошибка операции с историей статусов."""


class ConfirmationRequiredError(StatusHistoryError):
    """План требует явного подтверждения (ANCHOR_CORE §3)."""

    def __init__(self, plan: StatusAssignmentPlan) -> None:
        super().__init__("status assignment requires confirmation")
        self.plan = plan


class StatusHistoryService:
    """Жизненный цикл статусов с append-only историей и корректировками."""

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
        self._audit = UserActionLogRepository(conn)
        self._history = StatusHistoryRepository(conn)
        self._corrections = StatusHistoryCorrectionRepository(conn)
        self._statuses = AvailabilityStatusRepository(conn)
        self._employees = EmployeeRepository(conn)

    def list_history(self, employee_id: int) -> list[StatusHistoryEntry]:
        self._require(Permission.VIEW_STATUSES)
        self._require_employee(employee_id)
        return self._entries(employee_id)

    def current_status(
        self,
        employee_id: int,
        *,
        as_of: str | None = None,
    ) -> StatusHistoryEntry | None:
        self._require(Permission.VIEW_STATUSES)
        self._require_employee(employee_id)
        as_of_date = (as_of or self._clock()[:10])
        rows = self._entries(employee_id)
        corrections = self._correction_proposals(employee_id)
        return current_status_at(rows, corrections, as_of_date)

    def propose_assign_status(
        self,
        employee_id: int,
        *,
        status_id: int,
        start_date: str,
        end_date: str | None = None,
        note: str | None = None,
    ) -> StatusAssignmentPlan:
        self._require(Permission.MANAGE_STATUSES)
        self._require_employee(employee_id)
        status = self._require_active_status(status_id)
        self._validate_end_date_policy(status.end_date_policy, end_date)
        return plan_status_assignment(
            self._entries(employee_id),
            status_id=status_id,
            start_date=start_date,
            end_date=end_date,
            note=note,
        )

    def assign_status(
        self,
        employee_id: int,
        *,
        status_id: int,
        start_date: str,
        end_date: str | None = None,
        note: str | None = None,
        confirmed: bool = False,
    ) -> int:
        """
        Назначить статус. Если план требует подтверждения — только при confirmed=True.
        Возвращает id первой вставленной записи истории.
        """
        plan = self.propose_assign_status(
            employee_id,
            status_id=status_id,
            start_date=start_date,
            end_date=end_date,
            note=note,
        )
        if plan.requires_confirmation and not confirmed:
            raise ConfirmationRequiredError(plan)
        return self._apply_plan(employee_id, plan)

    def apply_plan(
        self,
        employee_id: int,
        plan: StatusAssignmentPlan,
        *,
        confirmed: bool = False,
    ) -> int:
        self._require(Permission.MANAGE_STATUSES)
        self._require_employee(employee_id)
        if plan.requires_confirmation and not confirmed:
            raise ConfirmationRequiredError(plan)
        return self._apply_plan(employee_id, plan)

    def _apply_plan(self, employee_id: int, plan: StatusAssignmentPlan) -> int:
        now = self._clock()
        try:
            for corr in plan.corrections:
                self._corrections.add(
                    status_history_id=corr.status_history_id,
                    field_name=corr.field_name,
                    old_value=corr.old_value,
                    new_value=corr.new_value,
                    reason=corr.reason,
                    created_at=now,
                    created_by_account_id=self._session.account_id,
                )
            first_id: int | None = None
            for insert in plan.inserts:
                row_id = self._history.add(
                    employee_id=employee_id,
                    status_id=insert.status_id,
                    start_date=insert.start_date,
                    end_date=insert.end_date,
                    note=insert.note,
                    created_at=now,
                    created_by_account_id=self._session.account_id,
                )
                if first_id is None:
                    first_id = row_id
            if first_id is None:
                raise StatusHistoryError("plan has no inserts")
            details = (
                f"inserts={len(plan.inserts)};corrections={len(plan.corrections)};"
                f"confirmed={int(plan.requires_confirmation)}"
            )
            self._audit.record(
                account_id=self._session.account_id,
                action_type="status.assign",
                result="success",
                created_at=now,
                entity_type="employee",
                entity_id=employee_id,
                details=details,
            )
            self._conn.commit()
            return first_id
        except Exception:
            self._conn.rollback()
            raise

    def effective_timeline(self, employee_id: int) -> list[StatusHistoryEntry]:
        self._require(Permission.VIEW_STATUSES)
        self._require_employee(employee_id)
        rows = self._entries(employee_id)
        corrections = self._correction_proposals(employee_id)
        return build_effective_timeline(rows, corrections)

    def _entries(self, employee_id: int) -> list[StatusHistoryEntry]:
        return [
            StatusHistoryEntry(
                id=r.id,
                status_id=r.status_id,
                start_date=r.start_date,
                end_date=r.end_date,
            )
            for r in self._history.list_for_employee(employee_id)
        ]

    def _correction_proposals(self, employee_id: int) -> list[StatusCorrectionProposal]:
        return [
            StatusCorrectionProposal(
                status_history_id=r.status_history_id,
                field_name=r.field_name,
                old_value=r.old_value,
                new_value=r.new_value,
                reason=r.reason,
            )
            for r in self._corrections.list_for_employee(employee_id)
        ]

    @staticmethod
    def _validate_end_date_policy(policy: int, end_date: str | None) -> None:
        if policy == 1 and end_date is None:
            raise StatusHistoryError("end_date required for this status")

    def _require(self, permission: Permission) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, permission)

    def _require_employee(self, employee_id: int) -> None:
        if self._employees.get(employee_id) is None:
            raise StatusHistoryError("employee not found")

    def _require_active_status(self, status_id: int):
        row = self._statuses.get(status_id)
        if row is None:
            raise StatusHistoryError("status not found")
        if row.is_archived:
            raise StatusHistoryError("archived status cannot be assigned")
        return row


__all__ = [
    "AuthorizationError",
    "ConfirmationRequiredError",
    "StatusHistoryError",
    "StatusHistoryService",
]
