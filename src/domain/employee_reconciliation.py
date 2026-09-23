"""Employee identity matching for directory-sync packages (ADR-0006 algorithm).

Read-only classification only: never applies creates, updates, or archives.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EmployeeMatchStatus(StrEnum):
    EXACT = "exact"  # external_id found locally, name corroborates
    CONFLICT = "conflict"  # external_id found locally, name does NOT match
    LOW = "low"  # no external_id match; exactly one name+dept+div candidate locally
    AMBIGUOUS = "ambiguous"  # no external_id match; more than one candidate
    NEW = "new"  # no external_id match; no candidates at all


@dataclass(frozen=True)
class EmployeeMatchCandidate:
    package_row: dict[str, object]
    status: EmployeeMatchStatus
    matched_employee_id: int | None
    candidate_employee_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class EmployeeSyncConflictDetail:
    external_id: str
    full_name: str
    status: EmployeeMatchStatus
    matched_employee_id: int | None = None


class EmployeeSyncConflictError(Exception):
    """Package employee rows cannot be applied automatically — nothing written."""

    def __init__(self, details: list[EmployeeSyncConflictDetail]) -> None:
        self.details = details
        super().__init__(f"{len(details)} employee row(s) blocked sync apply")


class EmployeeSyncApplyError(Exception):
    """Validation failed for one or more employee rows — nothing written."""
