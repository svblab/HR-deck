-- E1-08 / ADR-0010 §4: employment_types owner_branch_id, sort_order,
-- drop column UNIQUE on code; two partial unique indexes.
-- Rebuild in one runner transaction (foreign keys stay enforced on the
-- connection). This file does not disable FK enforcement, does not turn
-- deferred FKs back off, and does not run a foreign-key check pragma.

PRAGMA defer_foreign_keys=ON;

CREATE TEMP TABLE _employment_types_backup AS SELECT * FROM employment_types;

DROP TABLE employment_types;

CREATE TABLE employment_types (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archives_record INTEGER NOT NULL DEFAULT 0 CHECK (archives_record IN (0, 1)),
    owner_branch_id INTEGER NULL REFERENCES branches(id),
    sort_order INTEGER NOT NULL DEFAULT 0
);

INSERT INTO employment_types (
    id, code, name, is_archived, created_at, updated_at,
    owner_branch_id, archives_record, sort_order
)
SELECT
    id, code, name, is_archived, created_at, updated_at,
    NULL, archives_record, 0
FROM _employment_types_backup;

CREATE UNIQUE INDEX idx_employment_types_system_code
    ON employment_types(code) WHERE owner_branch_id IS NULL;

CREATE UNIQUE INDEX idx_employment_types_owner_code
    ON employment_types(owner_branch_id, code) WHERE owner_branch_id IS NOT NULL;

DROP TABLE _employment_types_backup;
