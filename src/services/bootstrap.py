"""Первичная настройка Администратора и восстановление по резерву (ADR-0003/0004)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from data.accounts import AccountRepository, RecoveryCodeRepository
from data.db import Connection, create_database, generate_master_key
from data.keywrap import (
    KeywrapError,
    KeywrapFile,
    find_recovery_wrap,
    keywrap_path_for,
    load_keywrap,
    replace_recovery_wrap,
    save_keywrap,
    unwrap_secret,
    upsert_account_wrap,
    wrap_secret,
)
from data.migrations import apply_pending_migrations
from data.repositories import TechnicalEventRepository, UserActionLogRepository
from domain.password_kdf import generate_recovery_code, hash_password, verify_password
from domain.permissions import RoleCode
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class BootstrapError(Exception):
    """Ошибка первичной настройки или восстановления."""


class BootstrapService:
    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or _utc_now

    def needs_setup(self, db_path: Path | str) -> bool:
        path = Path(db_path)
        wrap = keywrap_path_for(path)
        return not path.is_file() or not wrap.is_file()

    def initial_administrator_setup(
        self,
        *,
        db_path: Path | str,
        login: str,
        password: str,
    ) -> tuple[Connection, SessionState, str]:
        """
        Создать БД, Администратора и резервный код.

        Возвращает (conn, session, recovery_code_plaintext).
        Plaintext кода — только здесь для однократного показа; в БД/логах не пишется.
        """
        path = Path(db_path)
        wrap_path = keywrap_path_for(path)
        if path.exists() or wrap_path.exists():
            raise BootstrapError("application already initialized")
        if not login.strip() or not password:
            raise BootstrapError("login and password are required")

        master_key = generate_master_key()
        recovery_code = generate_recovery_code()
        now = self._clock()

        conn = create_database(path, master_key)
        apply_pending_migrations(conn)

        password_hash = hash_password(password)
        recovery_hash = hash_password(recovery_code)
        accounts = AccountRepository(conn)
        account_id = accounts.create(
            login=login.strip(),
            password_hash=password_hash,
            role=RoleCode.ADMINISTRATOR,
            created_at=now,
        )
        RecoveryCodeRepository(conn).insert(code_hash=recovery_hash, created_at=now)

        UserActionLogRepository(conn).record(
            account_id=account_id,
            action_type="account.create",
            result="success",
            created_at=now,
            entity_type="account",
            entity_id=account_id,
            details="role=administrator;initial_setup=1",
        )
        TechnicalEventRepository(conn).record(
            event_type="bootstrap.initial_admin",
            message="initial administrator created",
            created_at=now,
        )
        conn.commit()

        keywrap = KeywrapFile(
            wraps=[
                wrap_secret(master_key, password, kind="account", login=login.strip()),
                wrap_secret(master_key, recovery_code, kind="recovery"),
            ]
        )
        save_keywrap(wrap_path, keywrap)

        session = SessionState(
            account_id=account_id,
            login=login.strip(),
            role=RoleCode.ADMINISTRATOR,
            master_key=master_key,
        )
        return conn, session, recovery_code

    def recover_administrator_password(
        self,
        *,
        db_path: Path | str,
        recovery_code: str,
        new_password: str,
    ) -> str:
        """
        Сброс пароля Администратора по одноразовому коду.

        Возвращает новый plaintext recovery code для однократного показа.
        """
        if not recovery_code or not new_password:
            raise BootstrapError("recovery code and new password are required")

        path = Path(db_path)
        wrap_path = keywrap_path_for(path)
        try:
            keywrap = load_keywrap(wrap_path)
            recovery_wrap = find_recovery_wrap(keywrap)
            if recovery_wrap is None:
                raise BootstrapError("recovery is not available")
            master_key = unwrap_secret(recovery_wrap, recovery_code)
        except KeywrapError as exc:
            raise BootstrapError("invalid recovery code") from exc

        from data.db import connect

        conn = connect(path, master_key)
        try:
            return self._complete_recovery(
                conn,
                wrap_path,
                keywrap,
                master_key,
                recovery_code,
                new_password,
            )
        finally:
            conn.close()

    def _complete_recovery(
        self,
        conn: Connection,
        wrap_path: Path,
        keywrap: KeywrapFile,
        master_key: bytes,
        recovery_code: str,
        new_password: str,
    ) -> str:
        now = self._clock()
        recovery_repo = RecoveryCodeRepository(conn)
        matched_id: int | None = None
        for rid, code_hash in recovery_repo.list_active():
            if verify_password(code_hash, recovery_code):
                matched_id = rid
                break
        if matched_id is None:
            raise BootstrapError("invalid recovery code")

        accounts = AccountRepository(conn)
        admins = [
            a
            for a in accounts.list_accounts()
            if a.role_code == RoleCode.ADMINISTRATOR.value and a.is_active
        ]
        if not admins:
            raise BootstrapError("no active administrator")
        if len(admins) > 1:
            raise BootstrapError("multiple active administrators")
        admin = admins[0]

        new_hash = hash_password(new_password)
        accounts.set_password_hash(admin.id, new_hash, now)
        recovery_repo.mark_consumed(matched_id, now)

        new_code = generate_recovery_code()
        new_code_hash = hash_password(new_code)
        recovery_repo.insert(code_hash=new_code_hash, created_at=now)

        UserActionLogRepository(conn).record(
            account_id=admin.id,
            action_type="account.recover_password",
            result="success",
            created_at=now,
            entity_type="account",
            entity_id=admin.id,
            details="via_recovery_code=1",
        )
        TechnicalEventRepository(conn).record(
            event_type="auth.recovery",
            message="administrator password recovered; prior recovery code consumed",
            created_at=now,
        )
        conn.commit()

        updated = upsert_account_wrap(
            keywrap,
            wrap_secret(master_key, new_password, kind="account", login=admin.login),
        )
        updated = replace_recovery_wrap(
            updated,
            wrap_secret(master_key, new_code, kind="recovery"),
        )
        save_keywrap(wrap_path, updated)
        return new_code
