-- EPIC-024: optional department for employees (ADR-0008).
-- Table rebuild with FK enforcement on (migrations run inside a transaction).

DROP TRIGGER IF EXISTS trg_employees_org_consistency_insert;
DROP TRIGGER IF EXISTS trg_employees_org_consistency_update;
DROP TRIGGER IF EXISTS trg_divisions_no_rebranch_if_referenced;
DROP TRIGGER IF EXISTS trg_departments_no_reparent_if_referenced;

CREATE TEMP TABLE _adr0008_status_history_backup AS
    SELECT * FROM status_history;

DELETE FROM status_history;

CREATE TABLE employees_new (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    department_id INTEGER REFERENCES departments(id),
    division_id INTEGER REFERENCES divisions(id),
    employment_type_id INTEGER NOT NULL REFERENCES employment_types(id),
    note TEXT,
    hire_date TEXT,
    contacts TEXT,
    home_address TEXT,
    social_insurance_number TEXT,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO employees_new SELECT * FROM employees;

DROP TABLE employees;
ALTER TABLE employees_new RENAME TO employees;

INSERT INTO status_history SELECT * FROM _adr0008_status_history_backup;

CREATE INDEX idx_employees_branch ON employees(branch_id);
CREATE INDEX idx_employees_department ON employees(department_id);
CREATE INDEX idx_employees_full_name ON employees(full_name);

CREATE TRIGGER trg_employees_org_consistency_insert
BEFORE INSERT ON employees
BEGIN
    SELECT RAISE(ABORT, 'employee department does not belong to branch')
    WHERE NEW.department_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM departments d
        WHERE d.id = NEW.department_id AND d.branch_id = NEW.branch_id
      );

    SELECT RAISE(ABORT, 'employee division inconsistent with branch/department')
    WHERE NEW.division_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM divisions v
        WHERE v.id = NEW.division_id
          AND v.branch_id = NEW.branch_id
          AND (
            (v.department_id IS NULL AND NEW.department_id IS NULL)
            OR v.department_id = NEW.department_id
          )
      );
END;

CREATE TRIGGER trg_employees_org_consistency_update
BEFORE UPDATE OF branch_id, department_id, division_id ON employees
BEGIN
    SELECT RAISE(ABORT, 'employee department does not belong to branch')
    WHERE NEW.department_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM departments d
        WHERE d.id = NEW.department_id AND d.branch_id = NEW.branch_id
      );

    SELECT RAISE(ABORT, 'employee division inconsistent with branch/department')
    WHERE NEW.division_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM divisions v
        WHERE v.id = NEW.division_id
          AND v.branch_id = NEW.branch_id
          AND (
            (v.department_id IS NULL AND NEW.department_id IS NULL)
            OR v.department_id = NEW.department_id
          )
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
