-- Remove deprecated "Уволен / неактивен" availability status; dismissal uses
-- employment_type code "dismissed" instead (archive workflow rework).

DELETE FROM availability_statuses WHERE code = 'inactive';
