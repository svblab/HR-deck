"""Управление учётными записями — только Администратор; мутация + аудит атомарно."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from data.accounts import AccountRecord, AccountRepository, SettingsRepository
from data.db import Connection
from data.keywrap import (
    keywrap_path_for,
    load_keywrap,
    save_keywrap,
    upsert_account_wrap,
    wrap_secret,
)
from data.repositories import UserActionLogRepository
from domain.password_kdf import hash_password
from domain.permissions import Permission, RoleCode
from services.authorization import AuthorizationError, AuthorizationService
from services.session import SessionLockedError, SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class AccountView:
    id: int
    login: str
    role_code: str
    is_active: bool


class AccountManagementError(Exception):
    """Ошибка управления учётными записями."""


class AccountManagementService:
    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        db_path: Path | str,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._db_path = Path(db_path)
        self._authz = authz or AuthorizationService()
        self._clock: Clock = clock or _utc_now
        self._accounts = AccountRepository(conn)
        self._audit = UserActionLogRepository(conn)

    def list_accounts(self) -> list[AccountView]:
        self._guard(Permission.MANAGE_ACCOUNTS)
        return [
            AccountView(
                id=a.id,
                login=a.login,
                role_code=a.role_code,
                is_active=a.is_active,
            )
            for a in self._accounts.list_accounts()
        ]

    def create_account(
        self,
        *,
        login: str,
        password: str,
        role: RoleCode,
    ) -> int:
        self._guard(Permission.MANAGE_ACCOUNTS)
        login = login.strip()
        if not login or not password:
            raise AccountManagementError("login and password are required")
        if role not in RoleCode:
            raise AccountManagementError("invalid role")
        if self._accounts.get_by_login(login) is not None:
            raise AccountManagementError("login already exists")
        if role == RoleCode.ADMINISTRATOR:
            self._reject_second_active_administrator()

        now = self._clock()
        password_hash = hash_password(password)
        try:
            account_id = self._accounts.create(
                login=login,
                password_hash=password_hash,
                role=role,
                created_at=now,
            )
            self._audit.record(
                account_id=self._session.account_id,
                action_type="account.create",
                result="success",
                created_at=now,
                entity_type="account",
                entity_id=account_id,
                details=f"role={role.value}",
            )
            self._rewrite_account_wrap(login, password)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return account_id

    def set_role(self, account_id: int, role: RoleCode) -> None:
        self._guard(Permission.MANAGE_ACCOUNTS)
        target = self._require_account(account_id)
        if (
            role == RoleCode.ADMINISTRATOR
            and target.is_active
            and target.role_code != RoleCode.ADMINISTRATOR.value
        ):
            self._reject_second_active_administrator()
        if (
            target.role_code == RoleCode.ADMINISTRATOR.value
            and role != RoleCode.ADMINISTRATOR
            and target.is_active
            and self._accounts.count_active_administrators() <= 1
        ):
            raise AccountManagementError("cannot demote the last administrator")
        now = self._clock()
        try:
            self._accounts.set_role(account_id, role, now)
            self._audit.record(
                account_id=self._session.account_id,
                action_type="account.set_role",
                result="success",
                created_at=now,
                entity_type="account",
                entity_id=account_id,
                details=f"role={role.value}",
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def set_active(self, account_id: int, is_active: bool) -> None:
        self._guard(Permission.MANAGE_ACCOUNTS)
        target = self._require_account(account_id)
        if (
            is_active
            and target.role_code == RoleCode.ADMINISTRATOR.value
            and not target.is_active
        ):
            self._reject_second_active_administrator()
        if (
            not is_active
            and target.role_code == RoleCode.ADMINISTRATOR.value
            and target.is_active
            and self._accounts.count_active_administrators() <= 1
        ):
            raise AccountManagementError("cannot disable the last administrator")
        now = self._clock()
        try:
            self._accounts.set_active(account_id, is_active, now)
            self._audit.record(
                account_id=self._session.account_id,
                action_type="account.set_active",
                result="success",
                created_at=now,
                entity_type="account",
                entity_id=account_id,
                details=f"is_active={1 if is_active else 0}",
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def reset_password(self, account_id: int, new_password: str) -> None:
        self._guard(Permission.MANAGE_ACCOUNTS)
        target = self._require_account(account_id)
        if not new_password:
            raise AccountManagementError("password is required")
        now = self._clock()
        password_hash = hash_password(new_password)
        try:
            self._accounts.set_password_hash(account_id, password_hash, now)
            self._audit.record(
                account_id=self._session.account_id,
                action_type="account.reset_password",
                result="success",
                created_at=now,
                entity_type="account",
                entity_id=account_id,
            )
            self._rewrite_account_wrap(target.login, new_password)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def update_security_settings(
        self,
        *,
        inactivity_timeout_seconds: int | None = None,
        inactivity_timeout_enabled: bool | None = None,
        login_failure_delay_seconds: int | None = None,
        login_failure_delay_enabled: bool | None = None,
    ) -> None:
        self._guard(Permission.MANAGE_SECURITY_SETTINGS)
        settings = SettingsRepository(self._conn)
        now = self._clock()
        try:
            if inactivity_timeout_seconds is not None:
                if inactivity_timeout_seconds < 0:
                    raise AccountManagementError("invalid inactivity timeout")
                settings.set("inactivity_timeout_seconds", str(inactivity_timeout_seconds))
                self._session.inactivity_timeout_seconds = inactivity_timeout_seconds
            if inactivity_timeout_enabled is not None:
                settings.set(
                    "inactivity_timeout_enabled",
                    "1" if inactivity_timeout_enabled else "0",
                )
                self._session.inactivity_timeout_enabled = inactivity_timeout_enabled
            if login_failure_delay_seconds is not None:
                if login_failure_delay_seconds < 0:
                    raise AccountManagementError("invalid login delay")
                settings.set(
                    "login_failure_delay_seconds",
                    str(login_failure_delay_seconds),
                )
            if login_failure_delay_enabled is not None:
                settings.set(
                    "login_failure_delay_enabled",
                    "1" if login_failure_delay_enabled else "0",
                )
            self._audit.record(
                account_id=self._session.account_id,
                action_type="security.settings_update",
                result="success",
                created_at=now,
                entity_type="app_settings",
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get_security_settings(self) -> dict[str, int | bool]:
        self._guard(Permission.MANAGE_SECURITY_SETTINGS)
        settings = SettingsRepository(self._conn)
        return {
            "inactivity_timeout_seconds": settings.get_int("inactivity_timeout_seconds", 900),
            "inactivity_timeout_enabled": settings.get_bool("inactivity_timeout_enabled", True),
            "login_failure_delay_seconds": settings.get_int("login_failure_delay_seconds", 2),
            "login_failure_delay_enabled": settings.get_bool("login_failure_delay_enabled", True),
        }

    def _guard(self, permission: Permission) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, permission)

    def _require_account(self, account_id: int) -> AccountRecord:
        account = self._accounts.get_by_id(account_id)
        if account is None:
            raise AccountManagementError("account not found")
        return account

    def _reject_second_active_administrator(self) -> None:
        if self._accounts.count_active_administrators() >= 1:
            raise AccountManagementError("only one active administrator is allowed")

    def _rewrite_account_wrap(self, login: str, password: str) -> None:
        wrap_path = keywrap_path_for(self._db_path)
        keywrap = load_keywrap(wrap_path)
        entry = wrap_secret(self._session.master_key, password, kind="account", login=login)
        save_keywrap(wrap_path, upsert_account_wrap(keywrap, entry))


# Re-export for callers that probe authorization without UI.
__all__ = [
    "AccountManagementError",
    "AccountManagementService",
    "AccountView",
    "AuthorizationError",
    "SessionLockedError",
]
