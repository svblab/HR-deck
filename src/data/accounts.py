"""Репозиторий учётных записей и настроек безопасности."""

from __future__ import annotations

from dataclasses import dataclass

from data.db import Connection
from domain.permissions import ROLE_IDS, RoleCode


@dataclass(frozen=True)
class AccountRecord:
    id: int
    login: str
    password_hash: str
    role_id: int
    role_code: str
    is_active: bool
    created_at: str
    updated_at: str


class AccountRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def count_administrators(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM accounts a "
            "JOIN roles r ON r.id = a.role_id WHERE r.code = ?",
            (RoleCode.ADMINISTRATOR.value,),
        ).fetchone()
        return int(row[0])

    def count_accounts(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM accounts").fetchone()
        return int(row[0])

    def get_by_login(self, login: str) -> AccountRecord | None:
        row = self._conn.execute(
            "SELECT a.id, a.login, a.password_hash, a.role_id, r.code, a.is_active,"
            " a.created_at, a.updated_at "
            "FROM accounts a JOIN roles r ON r.id = a.role_id WHERE a.login = ?",
            (login,),
        ).fetchone()
        return _row_to_account(row) if row else None

    def get_by_id(self, account_id: int) -> AccountRecord | None:
        row = self._conn.execute(
            "SELECT a.id, a.login, a.password_hash, a.role_id, r.code, a.is_active,"
            " a.created_at, a.updated_at "
            "FROM accounts a JOIN roles r ON r.id = a.role_id WHERE a.id = ?",
            (account_id,),
        ).fetchone()
        return _row_to_account(row) if row else None

    def list_accounts(self) -> list[AccountRecord]:
        rows = self._conn.execute(
            "SELECT a.id, a.login, a.password_hash, a.role_id, r.code, a.is_active,"
            " a.created_at, a.updated_at "
            "FROM accounts a JOIN roles r ON r.id = a.role_id ORDER BY a.login"
        ).fetchall()
        return [_row_to_account(r) for r in rows]

    def create(
        self,
        *,
        login: str,
        password_hash: str,
        role: RoleCode,
        created_at: str,
        is_active: bool = True,
    ) -> int:
        # password_salt column remains for schema compat; Argon2 PHC embeds salt.
        cur = self._conn.execute(
            "INSERT INTO accounts ("
            " login, password_hash, password_salt, role_id, is_active, created_at, updated_at"
            ") VALUES (?, ?, '', ?, ?, ?, ?)",
            (
                login,
                password_hash,
                ROLE_IDS[role],
                1 if is_active else 0,
                created_at,
                created_at,
            ),
        )
        return int(cur.lastrowid)

    def set_password_hash(self, account_id: int, password_hash: str, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE accounts SET password_hash = ?, password_salt = '', updated_at = ? "
            "WHERE id = ?",
            (password_hash, updated_at, account_id),
        )

    def set_role(self, account_id: int, role: RoleCode, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE accounts SET role_id = ?, updated_at = ? WHERE id = ?",
            (ROLE_IDS[role], updated_at, account_id),
        )

    def set_active(self, account_id: int, is_active: bool, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE accounts SET is_active = ?, updated_at = ? WHERE id = ?",
            (1 if is_active else 0, updated_at, account_id),
        )


class SettingsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return str(row[0])

    def get_int(self, key: str, default: int) -> int:
        raw = self.get(key)
        if raw is None:
            return default
        return int(raw)

    def get_bool(self, key: str, default: bool) -> bool:
        raw = self.get(key)
        if raw is None:
            return default
        return raw in ("1", "true", "True", "yes")

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


class RecoveryCodeRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert(self, *, code_hash: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO recovery_codes (code_hash, is_consumed, created_at, consumed_at) "
            "VALUES (?, 0, ?, NULL)",
            (code_hash, created_at),
        )
        return int(cur.lastrowid)

    def list_active(self) -> list[tuple[int, str]]:
        rows = self._conn.execute(
            "SELECT id, code_hash FROM recovery_codes WHERE is_consumed = 0 ORDER BY id"
        ).fetchall()
        return [(int(r[0]), str(r[1])) for r in rows]

    def mark_consumed(self, recovery_id: int, consumed_at: str) -> None:
        self._conn.execute(
            "UPDATE recovery_codes SET is_consumed = 1, consumed_at = ? WHERE id = ?",
            (consumed_at, recovery_id),
        )


def _row_to_account(row: tuple[object, ...]) -> AccountRecord:
    return AccountRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        login=str(row[1]),
        password_hash=str(row[2]),
        role_id=int(row[3]),  # type: ignore[arg-type]
        role_code=str(row[4]),
        is_active=bool(int(row[5])),  # type: ignore[arg-type]
        created_at=str(row[6]),
        updated_at=str(row[7]),
    )
