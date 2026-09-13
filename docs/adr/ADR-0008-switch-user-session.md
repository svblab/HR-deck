# ADR-0008: In-app user switch (session teardown and re-login)

Status: Proposed — awaiting human acceptance
Date: 2026-09-13
Author: Cursor (EPIC-022)
Affected EPIC: EPIC-022

## Context

Users must be able to log out and log in as a different account without
restarting the desktop process. The application already supports initial login
via `LoginDialog`, inactivity lock via `UnlockDialog` (same user only), and
`SessionState` with lock/unlock semantics. Switch-user must reuse these
patterns without weakening cryptographic or RBAC guarantees (ADR-0002,
ADR-0003, ADR-0004).

## Considered options

1. **Process exit + relaunch** — simple but poor UX; rejected by product.
2. **Modal login over existing session without teardown** — risks stale
   `master_key`, open dialogs, and service handles bound to the old session.
3. **Explicit teardown → `LoginDialog` → `_bind_session`** — mirrors startup
   binding, clears secrets, closes child UI, reuses existing auth services.

## Decision

Adopt option 3 in `MainWindow`:

- **`_teardown_session`:** call `AuthenticationService.logout`, close the DB
  connection, then `session.lock(clear_key=True)` so the previous user's
  `master_key` is zeroed before any new login.
- **`_close_child_dialogs`:** iterate top-level `QDialog` widgets and close
  them before showing login, so secondary UI cannot retain old session context.
- **`switch_user`:** after teardown, show modal `LoginDialog`; on success call
  `_bind_session(conn, session)` to rebuild roster and services; on cancel call
  `self.close()` — same outcome as cancelling login at startup (no anonymous
  shell).

Startup (`app.py`) constructs `MainWindow(conn=…, session=…)` and binds once
via `_bind_session` in `__init__`, avoiding duplicate placeholder widgets.

## Consequences

- Positive: one code path for initial session bind and post-switch bind;
  secrets and permissions cannot leak across users in one process.
- Negative: cancelling switch-user ends the application; acceptable parity with
  startup cancel.
- `ANCHOR_CORE` / crypto model unchanged; no schema migration.

## Verification

- `tests/unit/test_switch_user.py` — visibility, teardown, re-login, cancel,
  inactivity reset, child dialog closure, first-bind warning regression,
  single-roster startup layout.
- Existing `test_login_unlock_ui.py` and `test_session_timeout.py` must stay
  green (inactivity lock unchanged).
