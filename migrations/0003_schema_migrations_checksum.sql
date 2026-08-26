-- EPIC-002 hardening: store checksum of applied migration SQL.
-- Do not rewrite 0001; extend schema_migrations via a new versioned migration.

ALTER TABLE schema_migrations ADD COLUMN checksum TEXT;
