-- EPIC-011 Step 3: metadata per template version + generated report linkage (ADR-0005 addendum).

PRAGMA foreign_keys = ON;

ALTER TABLE report_template_versions ADD COLUMN contract_version TEXT NOT NULL DEFAULT '1.0';
ALTER TABLE report_template_versions ADD COLUMN binding_mode TEXT NOT NULL DEFAULT 'excel'
    CHECK (binding_mode IN ('excel', 'acroform', 'regions'));
ALTER TABLE report_template_versions ADD COLUMN manifest_path TEXT;

CREATE TABLE template_generated_reports (
    id INTEGER PRIMARY KEY,
    template_version_id INTEGER NOT NULL REFERENCES report_template_versions(id),
    output_path TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    generated_by_account_id INTEGER REFERENCES accounts(id)
);

CREATE INDEX idx_template_generated_reports_version
    ON template_generated_reports (template_version_id);
