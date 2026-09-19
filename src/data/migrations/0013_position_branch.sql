-- EPIC-026 Part 1: positions become branch-scoped (ADR-0010).

PRAGMA foreign_keys = OFF;

CREATE TABLE positions_new (
    id INTEGER PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    name TEXT NOT NULL,
    department_required INTEGER NOT NULL DEFAULT 0
        CHECK (department_required IN (0, 1)),
    division_required INTEGER NOT NULL DEFAULT 0
        CHECK (division_required IN (0, 1)),
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Deliberately selects NULL for branch_id: if `positions` is empty this
-- inserts zero rows and succeeds; if it has any rows, the NOT NULL
-- constraint on branch_id aborts the whole migration, because there is
-- no safe way to infer which branch an existing position belongs to.
INSERT INTO positions_new
    (id, branch_id, name, department_required, division_required,
     is_archived, created_at, updated_at)
SELECT id, NULL, name, department_required, division_required,
       is_archived, created_at, updated_at
FROM positions;

DROP TABLE positions;
ALTER TABLE positions_new RENAME TO positions;
CREATE INDEX idx_positions_branch ON positions(branch_id);

-- New consistency trigger: an employee's position must belong to the
-- employee's own branch (mirrors trg_employees_org_consistency_* from
-- 0004/0011 for department).
CREATE TRIGGER trg_employees_position_branch_insert
BEFORE INSERT ON employees
BEGIN
    SELECT RAISE(ABORT, 'employee position does not belong to branch')
    WHERE NOT EXISTS (
        SELECT 1 FROM positions p
        WHERE p.id = NEW.position_id AND p.branch_id = NEW.branch_id
    );
END;

CREATE TRIGGER trg_employees_position_branch_update
BEFORE UPDATE OF position_id, branch_id ON employees
BEGIN
    SELECT RAISE(ABORT, 'employee position does not belong to branch')
    WHERE NOT EXISTS (
        SELECT 1 FROM positions p
        WHERE p.id = NEW.position_id AND p.branch_id = NEW.branch_id
    );
END;

PRAGMA foreign_key_check;
PRAGMA foreign_keys = ON;
