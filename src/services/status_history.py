"""Сервис валидации периодов статусов перед записью в репозиторий."""

from __future__ import annotations

from data.db import Connection
from data.repositories import StatusHistoryRepository
from domain.status_periods import StatusPeriod, validate_new_status_period


class StatusHistoryService:
    """Domain-правила + запись через typed repository (без UI)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._repo = StatusHistoryRepository(conn)

    def list_periods(self, employee_id: int) -> list[StatusPeriod]:
        rows = self._conn.execute(
            "SELECT start_date, end_date FROM status_history WHERE employee_id = ?",
            (employee_id,),
        ).fetchall()
        return [StatusPeriod(start_date=r[0], end_date=r[1]) for r in rows]

    def add_period(
        self,
        *,
        employee_id: int,
        status_id: int,
        start_date: str,
        created_at: str,
        end_date: str | None = None,
        note: str | None = None,
        created_by_account_id: int | None = None,
    ) -> int:
        candidate = StatusPeriod(start_date=start_date, end_date=end_date)
        validate_new_status_period(self.list_periods(employee_id), candidate)
        return self._repo.add(
            employee_id=employee_id,
            status_id=status_id,
            start_date=start_date,
            end_date=end_date,
            note=note,
            created_at=created_at,
            created_by_account_id=created_by_account_id,
        )
