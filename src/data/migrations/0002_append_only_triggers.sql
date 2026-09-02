-- EPIC-002 hardening: append-only enforcement at DB level (ANCHOR_CORE A9).
-- Python repositories remain a second line of defense.

CREATE TRIGGER trg_status_history_no_update
BEFORE UPDATE ON status_history
BEGIN
    SELECT RAISE(ABORT, 'status_history is append-only: UPDATE forbidden');
END;

CREATE TRIGGER trg_status_history_no_delete
BEFORE DELETE ON status_history
BEGIN
    SELECT RAISE(ABORT, 'status_history is append-only: DELETE forbidden');
END;

CREATE TRIGGER trg_user_action_log_no_update
BEFORE UPDATE ON user_action_log
BEGIN
    SELECT RAISE(ABORT, 'user_action_log is append-only: UPDATE forbidden');
END;

CREATE TRIGGER trg_user_action_log_no_delete
BEFORE DELETE ON user_action_log
BEGIN
    SELECT RAISE(ABORT, 'user_action_log is append-only: DELETE forbidden');
END;

CREATE TRIGGER trg_technical_events_no_update
BEFORE UPDATE ON technical_events
BEGIN
    SELECT RAISE(ABORT, 'technical_events is append-only: UPDATE forbidden');
END;

CREATE TRIGGER trg_technical_events_no_delete
BEFORE DELETE ON technical_events
BEGIN
    SELECT RAISE(ABORT, 'technical_events is append-only: DELETE forbidden');
END;
