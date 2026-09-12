-- EPIC-019 Phase 0: TransportKeyStore schema skeleton (ADR-0007 v3).
-- PROPOSAL ONLY — service logic and enforcement triggers follow human approval.

PRAGMA foreign_keys = ON;

-- Local installation identity (protocol routing peer id for this copy).
CREATE TABLE transport_installation (
    installation_id TEXT PRIMARY KEY,
    display_label TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Own signing identity keypairs (Ed25519). Separate from bootstrap encryption.
CREATE TABLE transport_local_signing_keys (
    id INTEGER PRIMARY KEY,
    public_key BLOB NOT NULL,
    private_key BLOB NOT NULL,
    key_fingerprint TEXT NOT NULL UNIQUE,
    key_status TEXT NOT NULL DEFAULT 'active'
        CHECK (key_status IN ('active', 'superseded', 'lost', 'compromised')),
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    notes TEXT
);

CREATE UNIQUE INDEX idx_transport_local_signing_active
    ON transport_local_signing_keys (key_status)
    WHERE key_status = 'active';

-- Own bootstrap encryption identity keypairs (X25519). Separate from signing.
CREATE TABLE transport_local_bootstrap_keys (
    id INTEGER PRIMARY KEY,
    public_key BLOB NOT NULL,
    private_key BLOB NOT NULL,
    key_fingerprint TEXT NOT NULL UNIQUE,
    key_status TEXT NOT NULL DEFAULT 'active'
        CHECK (key_status IN ('active', 'superseded', 'lost', 'compromised')),
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    notes TEXT
);

CREATE UNIQUE INDEX idx_transport_local_bootstrap_active
    ON transport_local_bootstrap_keys (key_status)
    WHERE key_status = 'active';

-- Trusted peer public material from manual out-of-band bootstrap.
CREATE TABLE transport_peer_trust (
    id INTEGER PRIMARY KEY,
    peer_installation_id TEXT NOT NULL UNIQUE,
    display_label TEXT,
    signing_public_key BLOB NOT NULL,
    signing_key_fingerprint TEXT NOT NULL,
    signing_trust_status TEXT NOT NULL DEFAULT 'active'
        CHECK (signing_trust_status IN ('active', 'revoked', 'compromised')),
    bootstrap_public_key BLOB NOT NULL,
    bootstrap_key_fingerprint TEXT NOT NULL,
    bootstrap_trust_status TEXT NOT NULL DEFAULT 'active'
        CHECK (bootstrap_trust_status IN ('active', 'revoked', 'compromised')),
    trusted_at TEXT NOT NULL,
    revoked_at TEXT,
    notes TEXT
);

CREATE INDEX idx_transport_peer_trust_signing_fp
    ON transport_peer_trust (signing_key_fingerprint);

-- Per-direction transport chain state (duplex: independent rows per sender→recipient).
CREATE TABLE transport_direction_state (
    id INTEGER PRIMARY KEY,
    sender_installation_id TEXT NOT NULL,
    recipient_installation_id TEXT NOT NULL,
    peer_trust_id INTEGER NOT NULL REFERENCES transport_peer_trust(id),
    accepted_sequence INTEGER NOT NULL DEFAULT 0,
    current_wk_key_id INTEGER,
    direction_status TEXT NOT NULL DEFAULT 'active'
        CHECK (direction_status IN ('active', 'broken', 'reinit_required')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (sender_installation_id, recipient_installation_id)
);

CREATE INDEX idx_transport_direction_peer
    ON transport_direction_state (peer_trust_id);

-- WK chain material. key_id is globally unique within this installation (ADR-0007).
CREATE TABLE transport_wk_keys (
    id INTEGER PRIMARY KEY,
    key_id TEXT NOT NULL UNIQUE,
    direction_id INTEGER NOT NULL REFERENCES transport_direction_state(id),
    sequence_established INTEGER,
    wk_key_material BLOB NOT NULL,
    wk_role TEXT NOT NULL
        CHECK (wk_role IN ('active', 'historical', 'revoked', 'compromised', 'lost')),
    predecessor_key_id TEXT,
    created_at TEXT NOT NULL,
    retired_at TEXT
);

CREATE INDEX idx_transport_wk_keys_direction
    ON transport_wk_keys (direction_id, sequence_established);

CREATE INDEX idx_transport_wk_keys_role
    ON transport_wk_keys (direction_id, wk_role);

-- Package acceptance / replay / rejection records (freshness + idempotency).
CREATE TABLE transport_package_records (
    id INTEGER PRIMARY KEY,
    direction_id INTEGER NOT NULL REFERENCES transport_direction_state(id),
    package_id TEXT NOT NULL UNIQUE,
    sequence INTEGER NOT NULL,
    classification TEXT NOT NULL
        CHECK (classification IN (
            'accepted',
            'rejected',
            'replay_observed',
            'pending'
        )),
    rejection_reason TEXT,
    envelope_key_id TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    accepted_at TEXT
);

CREATE INDEX idx_transport_package_direction_seq
    ON transport_package_records (direction_id, sequence);

CREATE UNIQUE INDEX idx_transport_package_accepted_sequence
    ON transport_package_records (direction_id, sequence)
    WHERE classification = 'accepted';
