-- EPIC-026 Part 2: stable external_id for directory entities and employees (ADR-0010).
--
-- external_id stays nullable at the schema level (SQLite can't add NOT NULL
-- retroactively without a full table rebuild, and a rebuild isn't justified
-- here since the UNIQUE index is the load-bearing guarantee); every row is
-- backfilled by this migration and every future INSERT from the service layer
-- always supplies one — enforced at the application layer, not the schema,
-- for this one field specifically. This is a deliberate, documented exception
-- to this project's usual schema-first preference.

ALTER TABLE branches ADD COLUMN external_id TEXT;
ALTER TABLE departments ADD COLUMN external_id TEXT;
ALTER TABLE divisions ADD COLUMN external_id TEXT;
ALTER TABLE positions ADD COLUMN external_id TEXT;
ALTER TABLE employees ADD COLUMN external_id TEXT;

UPDATE branches SET external_id = (
    lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
    substr(hex(randomblob(2)), 2) || '-' ||
    substr('89ab', abs(random()) % 4 + 1, 1) ||
    substr(hex(randomblob(2)), 2) || '-' ||
    hex(randomblob(6)))
) WHERE external_id IS NULL;

UPDATE departments SET external_id = (
    lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
    substr(hex(randomblob(2)), 2) || '-' ||
    substr('89ab', abs(random()) % 4 + 1, 1) ||
    substr(hex(randomblob(2)), 2) || '-' ||
    hex(randomblob(6)))
) WHERE external_id IS NULL;

UPDATE divisions SET external_id = (
    lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
    substr(hex(randomblob(2)), 2) || '-' ||
    substr('89ab', abs(random()) % 4 + 1, 1) ||
    substr(hex(randomblob(2)), 2) || '-' ||
    hex(randomblob(6)))
) WHERE external_id IS NULL;

UPDATE positions SET external_id = (
    lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
    substr(hex(randomblob(2)), 2) || '-' ||
    substr('89ab', abs(random()) % 4 + 1, 1) ||
    substr(hex(randomblob(2)), 2) || '-' ||
    hex(randomblob(6)))
) WHERE external_id IS NULL;

UPDATE employees SET external_id = (
    lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
    substr(hex(randomblob(2)), 2) || '-' ||
    substr('89ab', abs(random()) % 4 + 1, 1) ||
    substr(hex(randomblob(2)), 2) || '-' ||
    hex(randomblob(6)))
) WHERE external_id IS NULL;

CREATE UNIQUE INDEX idx_branches_external_id ON branches(external_id);
CREATE UNIQUE INDEX idx_departments_external_id ON departments(external_id);
CREATE UNIQUE INDEX idx_divisions_external_id ON divisions(external_id);
CREATE UNIQUE INDEX idx_positions_external_id ON positions(external_id);
CREATE UNIQUE INDEX idx_employees_external_id ON employees(external_id);

PRAGMA foreign_key_check;
