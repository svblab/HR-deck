"""ADR-0012 lifecycle: L2 purge on authentication boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.import_sessions import ImportSessionRepository
from services.authentication import AuthenticationService
from services.bootstrap import BootstrapService

_HASH = "a" * 64
_T0 = "2026-09-25T10:00:00Z"


@pytest.mark.acceptance
def test_login_purges_all_import_sessions(tmp_path: Path) -> None:
    clock = lambda: _T0  # noqa: E731
    db = tmp_path / "app.db"
    conn, _session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    sessions = ImportSessionRepository(conn)
    sessions.create_session(file_content_hash=_HASH, last_accessed_at=_T0)
    conn.commit()
    conn.close()

    auth = AuthenticationService(sleeper=lambda _s: None, clock=clock)
    conn2, _session2 = auth.login(db_path=db, login="admin", password="AdminPass-1")
    assert ImportSessionRepository(conn2).get_by_file_content_hash(_HASH) is None
    conn2.close()


@pytest.mark.acceptance
def test_logout_purges_all_import_sessions(tmp_path: Path) -> None:
    clock = lambda: _T0  # noqa: E731
    db = tmp_path / "app.db"
    BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )

    auth = AuthenticationService(sleeper=lambda _s: None, clock=clock)
    conn, session = auth.login(db_path=db, login="admin", password="AdminPass-1")
    sessions = ImportSessionRepository(conn)
    sessions.create_session(file_content_hash=_HASH, last_accessed_at=_T0)
    conn.commit()

    auth.logout(session, conn)
    assert ImportSessionRepository(conn).get_by_file_content_hash(_HASH) is None
    conn.close()
