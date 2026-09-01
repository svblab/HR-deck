-- EPIC-006: append-only corrections for status period adjustments (ANCHOR_CORE §3 / A9).
-- Auto-close and backdate adjustments are recorded here; status_history rows stay immutable.

CREATE TABLE status_history_corrections (
    id INTEGER PRIMARY KEY,
    status_history_id INTEGER NOT NULL REFERENCES status_history(id),
    field_name TEXT NOT NULL CHECK (field_name IN ('start_date', 'end_date')),
    old_value TEXT,
    new_value TEXT,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by_account_id INTEGER REFERENCES accounts(id)
);

CREATE INDEX idx_status_history_corrections_history
    ON status_history_corrections(status_history_id);

-- Overlap / one-open checks use effective timeline in the service layer.
DROP TRIGGER IF EXISTS trg_status_history_no_overlap_insert;
DROP TRIGGER IF EXISTS trg_status_history_one_open_insert;

CREATE TRIGGER trg_status_history_corrections_no_update
BEFORE UPDATE ON status_history_corrections
BEGIN
    SELECT RAISE(ABORT, 'status_history_corrections is append-only: UPDATE forbidden');
END;

CREATE TRIGGER trg_status_history_corrections_no_delete
BEFORE DELETE ON status_history_corrections
BEGIN
    SELECT RAISE(ABORT, 'status_history_corrections is append-only: DELETE forbidden');
END;
