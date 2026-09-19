-- EPIC-026 Part 3: table-level sync watermarks for directory export (ADR-0010).
--
-- Keyed by direction_id (FK to transport_direction_state), matching how this
-- project's transport layer already scopes per-peer-relationship state
-- (transport_wk_keys.direction_id, transport_package_records.direction_id).
-- Not peer_signing_fingerprint — that ADR draft was corrected against the
-- live schema before implementation.

CREATE TABLE sync_watermarks (
    direction_id INTEGER NOT NULL
        REFERENCES transport_direction_state(id) ON DELETE RESTRICT,
    table_name TEXT NOT NULL,
    last_exported_at TEXT NOT NULL,
    PRIMARY KEY (direction_id, table_name)
);
