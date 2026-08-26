"""Контекст аутентифицированной сессии и автоблокировка по бездействию."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from domain.permissions import RoleCode


class SessionLockedError(RuntimeError):
    """Сессия заблокирована — защищённые операции недоступны."""


class SessionError(RuntimeError):
    """Ошибка состояния сессии."""


@dataclass
class SessionState:
    account_id: int
    login: str
    role: RoleCode
    master_key: bytes
    locked: bool = False
    last_activity_mono: float = field(default_factory=monotonic)
    inactivity_timeout_seconds: int = 900
    inactivity_timeout_enabled: bool = True

    def touch(self, now_mono: float | None = None) -> None:
        if not self.locked:
            self.last_activity_mono = monotonic() if now_mono is None else now_mono

    def lock(self) -> None:
        self.locked = True

    def unlock(self, now_mono: float | None = None) -> None:
        self.locked = False
        self.touch(now_mono)

    def check_inactivity(self, now_mono: float | None = None) -> bool:
        """
        Если таймаут истёк — перевести в locked и вернуть True.
        Без реальных sleep: вызывающий передаёт monotonic-время в тестах.
        """
        if self.locked or not self.inactivity_timeout_enabled:
            return self.locked
        now = monotonic() if now_mono is None else now_mono
        elapsed = now - self.last_activity_mono
        if elapsed >= self.inactivity_timeout_seconds:
            self.lock()
            return True
        return False

    def require_unlocked(self, now_mono: float | None = None) -> None:
        self.check_inactivity(now_mono)
        if self.locked:
            raise SessionLockedError("session is locked")
