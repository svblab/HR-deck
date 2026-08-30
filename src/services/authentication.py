"""Аутентификация, задержка после неудачи, разблокировка сессии (ADR-0004)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import NoReturn

from data.accounts import AccountRepository, SettingsRepository
from data.db import Connection, connect
from data.keywrap import (
    KeywrapError,
    find_account_wrap,
    keywrap_path_for,
    load_keywrap,
    unwrap_secret,
)
from data.repositories import TechnicalEventRepository, UserActionLogRepository
from domain.password_kdf import verify_password
from domain.permissions import RoleCode
from services.session import SessionLockedError, SessionState

Sleeper = Callable[[float], None]
Clock = Callable[[], str]

_DEFAULT_DELAY = (True, 2.0)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class AuthenticationError(Exception):
    """Неуспешный вход/разблокировка. Сообщение без секретов и без enumeration."""


class AuthenticationService:
    """
    Вход и разблокировка. Задержка после неудачи — здесь, не в UI.
    Не логирует пароли.
    """

    def __init__(
        self,
        *,
        sleeper: Sleeper | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._sleep: Sleeper = sleeper or sleep
        self._clock: Clock = clock or _utc_now

    def login(
        self,
        *,
        db_path: Path | str,
        login: str,
        password: str,
    ) -> tuple[Connection, SessionState]:
        path = Path(db_path)
        wrap_path = keywrap_path_for(path)
        delay = _DEFAULT_DELAY
        conn: Connection | None = None

        try:
            keywrap = load_keywrap(wrap_path)
            entry = find_account_wrap(keywrap, login)
            if entry is None:
                self._fail(delay)
            try:
                master_key = unwrap_secret(entry, password)
            except KeywrapError:
                self._fail(delay)

            conn = connect(path, master_key)
            delay = self._delay_from_conn(conn)
            accounts = AccountRepository(conn)
            account = accounts.get_by_login(login)
            if account is None or not account.is_active:
                self._fail(delay, conn)
            if not verify_password(account.password_hash, password):
                self._fail(delay, conn)

            settings = SettingsRepository(conn)
            session = SessionState(
                account_id=account.id,
                login=account.login,
                role=RoleCode(account.role_code),
                master_key=master_key,
                inactivity_timeout_seconds=settings.get_int("inactivity_timeout_seconds", 900),
                inactivity_timeout_enabled=settings.get_bool("inactivity_timeout_enabled", True),
            )
            UserActionLogRepository(conn).record(
                account_id=account.id,
                action_type="session.login",
                result="success",
                created_at=self._clock(),
                entity_type="account",
                entity_id=account.id,
            )
            TechnicalEventRepository(conn).record(
                event_type="auth.login",
                message="login success",
                created_at=self._clock(),
            )
            conn.commit()
            return conn, session
        except AuthenticationError:
            raise
        except KeywrapError:
            self._fail(delay, conn)

    def unlock(
        self,
        session: SessionState,
        password: str,
        *,
        db_path: Path | str,
        conn: Connection | None = None,
    ) -> Connection:
        """
        Разблокировать сессию: повторный unwrap мастер-ключа и открытие БД.
        """
        if not session.locked:
            if conn is None:
                raise AuthenticationError("invalid credentials")
            return conn

        path = Path(db_path)
        delay = _DEFAULT_DELAY
        if conn is not None:
            delay = self._delay_from_conn(conn)
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

        try:
            keywrap = load_keywrap(keywrap_path_for(path))
            entry = find_account_wrap(keywrap, session.login)
            if entry is None:
                self._fail(delay)
            try:
                master_key = unwrap_secret(entry, password)
            except KeywrapError:
                self._fail(delay)

            new_conn = connect(path, master_key)
            delay = self._delay_from_conn(new_conn)
            accounts = AccountRepository(new_conn)
            account = accounts.get_by_id(session.account_id)
            if account is None or not account.is_active:
                self._fail(delay, new_conn)
            if not verify_password(account.password_hash, password):
                self._fail(delay, new_conn)

            session.master_key = master_key
            session.unlock()
            UserActionLogRepository(new_conn).record(
                account_id=session.account_id,
                action_type="session.unlock",
                result="success",
                created_at=self._clock(),
                entity_type="account",
                entity_id=session.account_id,
            )
            new_conn.commit()
            return new_conn
        except AuthenticationError:
            raise
        except KeywrapError:
            self._fail(delay)

    def logout(self, session: SessionState, conn: Connection) -> None:
        UserActionLogRepository(conn).record(
            account_id=session.account_id,
            action_type="session.logout",
            result="success",
            created_at=self._clock(),
            entity_type="account",
            entity_id=session.account_id,
        )
        conn.commit()
        session.lock(clear_key=True)

    def require_active_session(self, session: SessionState | None) -> SessionState:
        if session is None:
            raise SessionLockedError("no active session")
        session.require_unlocked()
        return session

    def _delay_from_conn(self, conn: Connection) -> tuple[bool, float]:
        settings = SettingsRepository(conn)
        enabled = settings.get_bool("login_failure_delay_enabled", True)
        seconds = float(settings.get_int("login_failure_delay_seconds", 2))
        return enabled, seconds

    def _fail(self, delay: tuple[bool, float], conn: Connection | None = None) -> NoReturn:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        enabled, seconds = delay
        if enabled and seconds > 0:
            self._sleep(seconds)
        raise AuthenticationError("invalid credentials")
