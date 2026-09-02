-- EPIC-002: forbid reparenting org nodes that are already referenced.
-- Prevents employees from becoming inconsistent when department/division parents move.

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

CREATE TRIGGER trg_divisions_no_reparent_if_referenced
BEFORE UPDATE OF department_id ON divisions
WHEN OLD.department_id != NEW.department_id
BEGIN
    SELECT RAISE(ABORT, 'cannot reparent division: referenced by employees')
    WHERE EXISTS (
        SELECT 1 FROM employees e WHERE e.division_id = OLD.id
    );
END;
