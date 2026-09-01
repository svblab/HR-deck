-- EPIC-003: security settings + one-time recovery code verifier (ADR-0004).

PRAGMA foreign_keys = ON;

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Defaults: 15 min inactivity; 2 s failed-login delay (ADR-0004).
INSERT INTO app_settings (key, value) VALUES
    ('inactivity_timeout_seconds', '900'),
    ('inactivity_timeout_enabled', '1'),
    ('login_failure_delay_seconds', '2'),
    ('login_failure_delay_enabled', '1');

-- Verifier only (Argon2id PHC). Plaintext recovery code is never stored.
CREATE TABLE recovery_codes (
    id INTEGER PRIMARY KEY,
    code_hash TEXT NOT NULL,
    is_consumed INTEGER NOT NULL DEFAULT 0 CHECK (is_consumed IN (0, 1)),
    created_at TEXT NOT NULL,
    consumed_at TEXT
);

CREATE INDEX idx_recovery_codes_active
    ON recovery_codes (is_consumed, id);
