-- E1-01 / ADR-0011 addendum §1.1: seed transferred and erroneous.
-- Contract check via TEMP BEFORE INSERT trigger; 0001 and 0017 untouched.

CREATE TEMP TABLE _employment_type_seed (
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    archives_record INTEGER NOT NULL,
    is_archived INTEGER NOT NULL
);

CREATE TEMP TRIGGER trg_employment_type_seed_contract
BEFORE INSERT ON _employment_type_seed
BEGIN
    SELECT RAISE(ABORT, 'employment type seed contract mismatch')
    WHERE EXISTS (
        SELECT 1 FROM employment_types e
        WHERE e.code = NEW.code
          AND (
              e.name IS NOT NEW.name
              OR e.archives_record IS NOT NEW.archives_record
              OR e.is_archived IS NOT NEW.is_archived
          )
    );
END;

INSERT INTO _employment_type_seed (code, name, archives_record, is_archived)
VALUES ('transferred', 'Переведён', 1, 0);

INSERT INTO _employment_type_seed (code, name, archives_record, is_archived)
VALUES ('erroneous', 'Ошибочная запись', 1, 0);

INSERT INTO employment_types (code, name, archives_record, is_archived, created_at, updated_at)
SELECT 'transferred', 'Переведён', 1, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'
WHERE NOT EXISTS (SELECT 1 FROM employment_types WHERE code = 'transferred');

INSERT INTO employment_types (code, name, archives_record, is_archived, created_at, updated_at)
SELECT 'erroneous', 'Ошибочная запись', 1, 0, '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z'
WHERE NOT EXISTS (SELECT 1 FROM employment_types WHERE code = 'erroneous');

DROP TRIGGER IF EXISTS trg_employment_type_seed_contract;
DROP TABLE IF EXISTS _employment_type_seed;
