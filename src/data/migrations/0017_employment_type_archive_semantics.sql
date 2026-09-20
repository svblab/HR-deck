-- ADR-0011: archive semantics on employment types + system seed dismissed.

ALTER TABLE employment_types ADD COLUMN archives_record INTEGER NOT NULL DEFAULT 0
    CHECK (archives_record IN (0, 1));

INSERT INTO employment_types (code, name, archives_record, is_archived, created_at, updated_at)
SELECT 'dismissed', 'Уволен', 1, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'
WHERE NOT EXISTS (SELECT 1 FROM employment_types WHERE code = 'dismissed');
