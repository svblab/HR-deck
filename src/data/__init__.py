"""Доступ к БД, миграции и репозитории."""

from data.db import (
    DatabaseError,
    IntegrityError,
    connect,
    create_database,
    generate_master_key,
    verify_integrity,
)
from data.migrations import (
    apply_pending_migrations,
    current_version,
    expected_migration_versions,
    repair_missing_checksums,
    validate_applied_migrations,
)

__all__ = [
    "DatabaseError",
    "IntegrityError",
    "apply_pending_migrations",
    "connect",
    "create_database",
    "current_version",
    "expected_migration_versions",
    "generate_master_key",
    "repair_missing_checksums",
    "validate_applied_migrations",
    "verify_integrity",
]
