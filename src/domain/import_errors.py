"""Stable import/sync error codes (ADR-0013 Checkpoint 2).

Human-readable explanations live in ``docs/import-error-codes.md``.
Runtime carries ``(ImportErrorCode, raw_message)`` only.
"""

from __future__ import annotations

from enum import StrEnum


class ImportErrorCode(StrEnum):
    PACKAGE_STALE_SEQUENCE = "IMP-001"
    EMPLOYEE_WOULD_BECOME_INVALID = "IMP-002"
    DIRECTORY_PLAN_REJECTED = "IMP-003"
    DUPLICATE_EXTERNAL_ID = "IMP-004"
    ARCHIVED_BRANCH = "IMP-005"
    ARCHIVED_POSITION = "IMP-006"
    ARCHIVED_DEPARTMENT = "IMP-007"
    ARCHIVED_DIVISION = "IMP-008"
    UNRESOLVED_BRANCH = "IMP-009"
    UNRESOLVED_POSITION = "IMP-010"
    UNRESOLVED_DEPARTMENT = "IMP-011"
    UNRESOLVED_DIVISION = "IMP-012"
    DEPARTMENT_WRONG_BRANCH = "IMP-013"
    DIVISION_WRONG_BRANCH = "IMP-014"
    DIVISION_WRONG_DEPARTMENT = "IMP-015"
    EMPLOYEE_CARD_INVALID = "IMP-016"
    EMPLOYEE_MATCH_CONFLICT = "IMP-017"
    EMPLOYEE_MATCH_LOW = "IMP-018"
    EMPLOYEE_MATCH_AMBIGUOUS = "IMP-019"


class CodedImportError(ValueError):
    """ValueError that also carries a stable ``ImportErrorCode``."""

    def __init__(self, code: ImportErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


ImportReason = tuple[ImportErrorCode, str]


def format_import_reason(reason: ImportReason) -> str:
    code, message = reason
    return f"{code.value}: {message}"


__all__ = [
    "CodedImportError",
    "ImportErrorCode",
    "ImportReason",
    "format_import_reason",
]
