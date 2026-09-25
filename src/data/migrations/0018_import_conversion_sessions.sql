-- EPIC-018: conversion wizard staging tables (ADR-0012).

CREATE TABLE import_sessions (
    id INTEGER PRIMARY KEY,
    file_content_hash TEXT NOT NULL UNIQUE,
    last_accessed_at TEXT NOT NULL
);

CREATE TABLE import_session_rows (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL
        REFERENCES import_sessions(id) ON DELETE CASCADE,
    source_row_number INTEGER NOT NULL,
    values_json TEXT NOT NULL,
    UNIQUE (session_id, source_row_number)
);

CREATE INDEX idx_import_sessions_last_accessed_at
    ON import_sessions (last_accessed_at);
