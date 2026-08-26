"""CRUD справочника статусов доступности с RBAC и аудитом (EPIC-006)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from data.availability_statuses import AvailabilityStatusRepository
from data.db import Connection
from data.repositories import UserActionLogRepository
from domain.permissions import Permission
from services.authorization import AuthorizationError, AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]

_END_DATE_POLICIES = frozenset({0, 1, 2})


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class AvailabilityStatusError(Exception):
    """Ошибка операции со справочником статусов."""


class AvailabilityStatusService:
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
        self._statuses = AvailabilityStatusRepository(conn)

    def list_statuses(self, *, active_only: bool = False):
        self._require(Permission.VIEW_STATUSES)
        return self._statuses.list(active_only=active_only)

    def create_status(
        self,
        *,
        code: str,
        name: str,
        end_date_policy: int = 0,
        color_hex: str | None = None,
        sort_order: int = 0,
    ) -> int:
        self._require(Permission.MANAGE_STATUSES)
        clean_code = _clean_code(code)
        clean_name = _clean_name(name)
        if end_date_policy not in _END_DATE_POLICIES:
            raise AvailabilityStatusError("invalid end_date_policy")
        if self._statuses.get_by_code(clean_code) is not None:
            raise AvailabilityStatusError("status code already exists")
        now = self._clock()
        return self._mutate(
            action="status.create",
            entity_type="availability_status",
            mutate=lambda: self._statuses.create(
                code=clean_code,
                name=clean_name,
                end_date_policy=end_date_policy,
                color_hex=color_hex,
                sort_order=sort_order,
                created_at=now,
            ),
            details=f"code={clean_code};name={clean_name}",
        )

    def rename_status(self, status_id: int, name: str) -> None:
        self._require(Permission.MANAGE_STATUSES)
        self._require_status(status_id)
        clean = _clean_name(name)
        now = self._clock()
        self._mutate(
            action="status.rename",
            entity_type="availability_status",
            entity_id=status_id,
            mutate=lambda: self._statuses.rename(status_id, name=clean, updated_at=now),
            details=f"name={clean}",
        )

    def update_status_display(
        self,
        status_id: int,
        *,
        color_hex: str | None,
        sort_order: int,
    ) -> None:
        self._require(Permission.MANAGE_STATUSES)
        self._require_status(status_id)
        now = self._clock()
        self._mutate(
            action="status.update_display",
            entity_type="availability_status",
            entity_id=status_id,
            mutate=lambda: self._statuses.update_display(
                status_id,
                color_hex=color_hex,
                sort_order=sort_order,
                updated_at=now,
            ),
            details=f"sort_order={sort_order}",
        )

    def archive_status(self, status_id: int) -> None:
        self._set_archived(status_id, archived=True)

    def unarchive_status(self, status_id: int) -> None:
        self._set_archived(status_id, archived=False)

    def _set_archived(self, status_id: int, *, archived: bool) -> None:
        self._require(Permission.MANAGE_STATUSES)
        self._require_status(status_id)
        now = self._clock()
        verb = "archive" if archived else "unarchive"
        self._mutate(
            action=f"status.{verb}",
            entity_type="availability_status",
            entity_id=status_id,
            mutate=lambda: self._statuses.set_archived(
                status_id, archived=archived, updated_at=now
            ),
        )

    def _require(self, permission: Permission) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, permission)

    def _require_status(self, status_id: int):
        row = self._statuses.get(status_id)
        if row is None:
            raise AvailabilityStatusError("status not found")
        return row

    def _mutate(
        self,
        *,
        action: str,
        entity_type: str,
        mutate: Callable[[], int | None],
        entity_id: int | None = None,
        details: str | None = None,
    ) -> int:
        now = self._clock()
        try:
            result = mutate()
            new_id = int(result) if result is not None else entity_id
            if new_id is None:
                raise AvailabilityStatusError("mutation did not yield entity id")
            self._audit.record(
                account_id=self._session.account_id,
                action_type=action,
                result="success",
                created_at=now,
                entity_type=entity_type,
                entity_id=new_id,
                details=details,
            )
            self._conn.commit()
            return new_id
        except Exception:
            self._conn.rollback()
            raise


def _clean_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        raise AvailabilityStatusError("name must not be empty")
    return clean


def _clean_code(code: str) -> str:
    clean = code.strip().lower()
    if not clean:
        raise AvailabilityStatusError("code must not be empty")
    return clean


__all__ = ["AuthorizationError", "AvailabilityStatusError", "AvailabilityStatusService"]
