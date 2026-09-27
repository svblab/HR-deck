-- Pre-021: per-direction transport generation (epoch) alongside sequence (ADR-0007 addendum).

PRAGMA foreign_keys = ON;

ALTER TABLE transport_direction_state
    ADD COLUMN generation INTEGER NOT NULL DEFAULT 0;

ALTER TABLE transport_package_records
    ADD COLUMN generation INTEGER NOT NULL DEFAULT 0;

ALTER TABLE transport_wk_keys
    ADD COLUMN generation_established INTEGER;

DROP INDEX IF EXISTS idx_transport_package_accepted_sequence;

CREATE UNIQUE INDEX idx_transport_package_accepted_sequence
    ON transport_package_records (direction_id, generation, sequence)
    WHERE classification = 'accepted';
