"""Журнал действий пользователей (ТЗ §4.6)."""

from __future__ import annotations

from dataclasses import dataclass

ENTITY_EMPLOYEE = "employee"
ENTITY_TEMPLATE = "report_template"

EXPORT_HEADERS = (
    "Дата/время",
    "Пользователь",
    "Тип действия",
    "Сущность",
    "ID",
    "Результат",
    "Детали",
)


@dataclass(frozen=True)
class ActionLogFilters:
    account_id: int | None = None
    created_from: str | None = None
    created_to: str | None = None
    action_type: str | None = None
    employee_id: int | None = None
    template_id: int | None = None
    entity_type: str | None = None


@dataclass(frozen=True)
class ActionLogEntry:
    id: int
    account_id: int | None
    account_login: str | None
    action_type: str
    entity_type: str | None
    entity_id: int | None
    result: str
    details: str | None
    created_at: str

    def export_cells(self) -> list[str]:
        entity_id = "" if self.entity_id is None else str(self.entity_id)
        return [
            self.created_at,
            self.account_login or "—",
            self.action_type,
            self.entity_type or "—",
            entity_id,
            self.result,
            self.details or "",
        ]
