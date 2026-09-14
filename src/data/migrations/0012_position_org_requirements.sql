-- EPIC-025: position org requirements and employee org-review flag (ADR-0009).

ALTER TABLE positions ADD COLUMN department_required INTEGER NOT NULL DEFAULT 0
    CHECK (department_required IN (0, 1));
ALTER TABLE positions ADD COLUMN division_required INTEGER NOT NULL DEFAULT 0
    CHECK (division_required IN (0, 1));
ALTER TABLE employees ADD COLUMN needs_org_review INTEGER NOT NULL DEFAULT 0
    CHECK (needs_org_review IN (0, 1));
