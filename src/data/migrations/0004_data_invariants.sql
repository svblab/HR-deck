-- EPIC-002 hardening: org hierarchy + status period invariants at DB level.

-- Employee.branch_id must match department.branch_id;
-- if division_id set, division.department_id must match employee.department_id.

CREATE TRIGGER trg_employees_org_consistency_insert
BEFORE INSERT ON employees
BEGIN
    SELECT RAISE(ABORT, 'employee department does not belong to branch')
    WHERE NOT EXISTS (
        SELECT 1 FROM departments d
        WHERE d.id = NEW.department_id AND d.branch_id = NEW.branch_id
    );

    SELECT RAISE(ABORT, 'employee division does not belong to department')
    WHERE NEW.division_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM divisions v
        WHERE v.id = NEW.division_id AND v.department_id = NEW.department_id
      );
END;

CREATE TRIGGER trg_employees_org_consistency_update
BEFORE UPDATE OF branch_id, department_id, division_id ON employees
BEGIN
    SELECT RAISE(ABORT, 'employee department does not belong to branch')
    WHERE NOT EXISTS (
        SELECT 1 FROM departments d
        WHERE d.id = NEW.department_id AND d.branch_id = NEW.branch_id
    );

    SELECT RAISE(ABORT, 'employee division does not belong to department')
    WHERE NEW.division_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM divisions v
        WHERE v.id = NEW.division_id AND v.department_id = NEW.department_id
      );
END;

-- Status history: date order, no overlaps, at most one open-ended period.

CREATE TRIGGER trg_status_history_date_order_insert
BEFORE INSERT ON status_history
BEGIN
    SELECT RAISE(ABORT, 'status start_date must be <= end_date')
    WHERE NEW.end_date IS NOT NULL AND NEW.start_date > NEW.end_date;
END;

CREATE TRIGGER trg_status_history_no_overlap_insert
BEFORE INSERT ON status_history
BEGIN
    SELECT RAISE(ABORT, 'overlapping status period for employee')
    WHERE EXISTS (
        SELECT 1 FROM status_history h
        WHERE h.employee_id = NEW.employee_id
          AND h.start_date <= COALESCE(NEW.end_date, '9999-12-31')
          AND NEW.start_date <= COALESCE(h.end_date, '9999-12-31')
    );
END;

CREATE TRIGGER trg_status_history_one_open_insert
BEFORE INSERT ON status_history
WHEN NEW.end_date IS NULL
BEGIN
    SELECT RAISE(ABORT, 'duplicate open-ended status for employee')
    WHERE EXISTS (
        SELECT 1 FROM status_history h
        WHERE h.employee_id = NEW.employee_id AND h.end_date IS NULL
    );
END;
