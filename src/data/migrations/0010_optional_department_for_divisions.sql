-- EPIC-024: optional department for divisions (ADR-0008).
-- Table rebuild with FK enforcement on (migrations run inside a transaction;
-- PRAGMA foreign_keys cannot be toggled mid-transaction).

DROP TRIGGER IF EXISTS trg_departments_no_reparent_if_referenced;
DROP TRIGGER IF EXISTS trg_divisions_no_reparent_if_referenced;
DROP TRIGGER IF EXISTS trg_employees_org_consistency_insert;
DROP TRIGGER IF EXISTS trg_employees_org_consistency_update;

CREATE TEMP TABLE _adr0008_emp_division_backup AS
    SELECT id, division_id FROM employees WHERE division_id IS NOT NULL;

UPDATE employees SET division_id = NULL WHERE division_id IS NOT NULL;

CREATE TABLE divisions_new (
    id INTEGER PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    department_id INTEGER REFERENCES departments(id),
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (branch_id, name)
);

INSERT INTO divisions_new
    (id, branch_id, department_id, name, is_archived, created_at, updated_at)
SELECT d.id, dep.branch_id, d.department_id, d.name, d.is_archived,
       d.created_at, d.updated_at
FROM divisions d
JOIN departments dep ON dep.id = d.department_id;

DROP TABLE divisions;
ALTER TABLE divisions_new RENAME TO divisions;

UPDATE employees
SET division_id = (
    SELECT b.division_id
    FROM _adr0008_emp_division_backup b
    WHERE b.id = employees.id
)
WHERE EXISTS (
    SELECT 1 FROM _adr0008_emp_division_backup b WHERE b.id = employees.id
);

CREATE INDEX idx_divisions_department ON divisions(department_id);
CREATE INDEX idx_divisions_branch ON divisions(branch_id);

CREATE TRIGGER trg_divisions_org_consistency_insert
BEFORE INSERT ON divisions
BEGIN
    SELECT RAISE(ABORT, 'division department does not belong to branch')
    WHERE NEW.department_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM departments d
        WHERE d.id = NEW.department_id AND d.branch_id = NEW.branch_id
      );
END;

CREATE TRIGGER trg_divisions_org_consistency_update
BEFORE UPDATE OF branch_id, department_id ON divisions
BEGIN
    SELECT RAISE(ABORT, 'division department does not belong to branch')
    WHERE NEW.department_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM departments d
        WHERE d.id = NEW.department_id AND d.branch_id = NEW.branch_id
      );
END;

CREATE TRIGGER trg_divisions_no_rebranch_if_referenced
BEFORE UPDATE OF branch_id ON divisions
WHEN OLD.branch_id != NEW.branch_id
BEGIN
    SELECT RAISE(ABORT, 'cannot move division to another branch: referenced by employees')
    WHERE EXISTS (SELECT 1 FROM employees e WHERE e.division_id = OLD.id);
END;

CREATE TRIGGER trg_departments_no_reparent_if_referenced
BEFORE UPDATE OF branch_id ON departments
WHEN OLD.branch_id != NEW.branch_id
BEGIN
    SELECT RAISE(ABORT, 'cannot reparent department: referenced by employees')
    WHERE EXISTS (
        SELECT 1 FROM employees e WHERE e.department_id = OLD.id
    );

    SELECT RAISE(ABORT, 'cannot reparent department: has child divisions')
    WHERE EXISTS (
        SELECT 1 FROM divisions v WHERE v.department_id = OLD.id
    );
END;

PRAGMA foreign_key_check;
