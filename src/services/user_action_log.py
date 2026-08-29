"""Просмотр журнала действий: только чтение, только Администратор (ТЗ §4.6)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from data.accounts import AccountRepository
from data.db import Connection
from data.employees import EmployeeRepository
from data.repositories import UserActionLogRepository
from domain.action_log import (
    ENTITY_EMPLOYEE,
    ENTITY_TEMPLATE,
    EXPORT_HEADERS,
    ActionLogEntry,
    ActionLogFilters,
)
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.employee_files import write_xlsx
from services.session import SessionState


class UserActionLogService:
    """Обёртка над append-only журналом. Методов записи нет — просмотр не аудируется."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
    ) -> None:
        self._session = session
        self._authz = authz or AuthorizationService()
        self._log = UserActionLogRepository(conn)
        self._accounts = AccountRepository(conn)
        self._employees = EmployeeRepository(conn)

    def list_entries(self, filters: ActionLogFilters | None = None) -> list[ActionLogEntry]:
        self._require()
        spec = filters or ActionLogFilters()
        if spec.employee_id is not None and spec.template_id is not None:
            return []
        entity_type, entity_id = _entity_scope(spec)
        return self._log.list_entries(
            account_id=spec.account_id,
            created_from=spec.created_from,
            created_to_exclusive=_exclusive_after(spec.created_to),
            action_type=spec.action_type,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    def list_action_types(self) -> list[str]:
        self._require()
        return self._log.list_action_types()

    def list_accounts(self) -> list[tuple[int, str]]:
        self._require()
        return [(a.id, a.login) for a in self._accounts.list_accounts()]

    def list_employees(self) -> list[tuple[int, str]]:
        self._require()
        return [(e.id, e.full_name) for e in self._employees.list(active_only=False)]

    def list_templates(self) -> list[tuple[int, str]]:
        """Размерность «шаблон»: entity_type уже в схеме; записи появятся в EPIC-011."""
        self._require()
        return self._log.list_template_refs()

    def export_xlsx(self, path: Path, filters: ActionLogFilters | None = None) -> int:
        entries = self.list_entries(filters)
        write_xlsx(path, list(EXPORT_HEADERS), [e.export_cells() for e in entries])
        return len(entries)

    def _require(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.VIEW_USER_ACTION_LOG)


def _entity_scope(spec: ActionLogFilters) -> tuple[str | None, int | None]:
    if spec.employee_id is not None:
        return ENTITY_EMPLOYEE, spec.employee_id
    if spec.template_id is not None:
        return ENTITY_TEMPLATE, spec.template_id
    return spec.entity_type, None


def _exclusive_after(day: str | None) -> str | None:
    if day is None:
        return None
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()
