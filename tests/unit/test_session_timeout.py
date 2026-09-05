"""Таймаут сессии без real-time sleep."""

from __future__ import annotations

import pytest

from domain.permissions import RoleCode
from services.session import SessionLockedError, SessionState


def _session(**kwargs: object) -> SessionState:
    defaults = {
        "account_id": 1,
        "login": "admin",
        "role": RoleCode.ADMINISTRATOR,
        "master_key": b"\x00" * 32,
        "last_activity_mono": 1_000.0,
        "inactivity_timeout_seconds": 900,
        "inactivity_timeout_enabled": True,
    }
    defaults.update(kwargs)
    return SessionState(**defaults)  # type: ignore[arg-type]


def test_default_timeout_locks_after_900s() -> None:
    s = _session()
    assert not s.check_inactivity(1_000.0 + 899)
    assert s.check_inactivity(1_000.0 + 900)
    assert s.locked
    assert s.master_key == b""


def test_activity_resets_timeout() -> None:
    s = _session()
    s.touch(1_500.0)
    assert not s.check_inactivity(1_500.0 + 899)
    assert s.check_inactivity(1_500.0 + 900)


def test_disabled_timeout_never_auto_locks() -> None:
    s = _session(inactivity_timeout_enabled=False)
    assert not s.check_inactivity(1_000.0 + 10_000)
    assert not s.locked


def test_zero_timeout_never_auto_locks() -> None:
    s = _session(inactivity_timeout_seconds=0)
    assert not s.check_inactivity(1_000.0 + 10_000)
    assert not s.locked
    assert not s.inactivity_lock_active


def test_configurable_timeout() -> None:
    s = _session(inactivity_timeout_seconds=60)
    assert s.check_inactivity(1_060.0)


def test_locked_blocks_protected_operations() -> None:
    s = _session()
    s.lock()
    with pytest.raises(SessionLockedError):
        s.require_unlocked()


def test_unlock_clears_lock() -> None:
    s = _session()
    s.lock()
    s.unlock(2_000.0)
    assert not s.locked
    s.require_unlocked(2_000.0)
