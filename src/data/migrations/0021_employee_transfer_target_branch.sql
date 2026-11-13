-- E1-05: nullable transfer target branch on employees (ADR-0011 addendum §3.2).

ALTER TABLE employees
    ADD COLUMN transfer_target_branch_id INTEGER REFERENCES branches(id);
