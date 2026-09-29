"""EPIC-018 / Issue #124: classify staged conversion rows for bulk apply (ADR-0012 addendum)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from data.import_sessions import ImportSessionRowRecord
from domain.employee import EmployeeCreateInput, normalize_name_for_match
from services.directories import DirectoryService
from services.employees import EmployeeError, EmployeeService, EmployeeValidationError

ReadinessKind = Literal["ready", "needs_review"]


@dataclass(frozen=True)
class ConversionBulkRowClassification:
    row_id: int
    source_row_number: int
    full_name: str
    kind: ReadinessKind
    resolved: EmployeeCreateInput | None


def _casefold_key(raw: str) -> str:
    return raw.strip().casefold()


def _unique_active_id(
    raw: str,
    entries: list[tuple[int, str, bool]],
) -> int | None:
    key = _casefold_key(raw)
    if not key:
        return None
    matches = [
        entity_id
        for entity_id, name, is_archived in entries
        if _casefold_key(name) == key and not is_archived
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _has_name_duplicate(employees: EmployeeService, full_name: str) -> bool:
    clean = full_name.strip()
    if not clean:
        return False
    needle = normalize_name_for_match(clean)
    return any(
        normalize_name_for_match(hit.full_name) == needle
        for hit in employees.search_by_name(clean)
    )


def _directory_entries(rows) -> list[tuple[int, str, bool]]:
    return [(row.id, row.name, row.is_archived) for row in rows]


def classify_conversion_rows(
    rows: list[ImportSessionRowRecord],
    *,
    directories: DirectoryService,
    employees: EmployeeService,
) -> list[ConversionBulkRowClassification]:
    branches = _directory_entries(directories.list_branches())
    employment_types = _directory_entries(directories.list_employment_types())
    classified: list[ConversionBulkRowClassification] = []

    for row in rows:
        values = json.loads(row.values_json)
        full_name = values.get("full_name", "")
        branch_id = _unique_active_id(values.get("branch", ""), branches)
        position_id: int | None = None
        department_id: int | None = None
        division_id: int | None = None
        employment_type_id = _unique_active_id(
            values.get("employment_type", ""), employment_types
        )

        ready = True
        if not full_name.strip():
            ready = False
        if branch_id is None:
            ready = False
        if employment_type_id is None:
            ready = False
        if branch_id is not None:
            positions = _directory_entries(
                directories.list_positions(branch_id=branch_id)
            )
            position_id = _unique_active_id(values.get("position", ""), positions)
            if position_id is None:
                ready = False

            dept_raw = values.get("department", "")
            if _casefold_key(dept_raw):
                departments = _directory_entries(
                    directories.list_departments(branch_id=branch_id)
                )
                department_id = _unique_active_id(dept_raw, departments)
                if department_id is None:
                    ready = False
            else:
                department_id = None

            div_raw = values.get("division", "")
            if _casefold_key(div_raw):
                if department_id is None:
                    ready = False
                else:
                    divisions = _directory_entries(
                        directories.list_divisions(
                            branch_id=branch_id, department_id=department_id
                        )
                    )
                    division_id = _unique_active_id(div_raw, divisions)
                    if division_id is None:
                        ready = False
            else:
                division_id = None

        if ready and _has_name_duplicate(employees, full_name):
            ready = False

        resolved: EmployeeCreateInput | None = None
        if ready and branch_id is not None and position_id is not None:
            assert employment_type_id is not None
            payload = EmployeeCreateInput(
                full_name=full_name.strip(),
                position_id=position_id,
                branch_id=branch_id,
                department_id=department_id,
                employment_type_id=employment_type_id,
                division_id=division_id,
                note=None,
            )
            try:
                resolved = employees.validate_card_input(payload)
            except (EmployeeError, EmployeeValidationError):
                ready = False
                resolved = None

        classified.append(
            ConversionBulkRowClassification(
                row_id=row.id,
                source_row_number=row.source_row_number,
                full_name=full_name.strip() or "—",
                kind="ready" if ready and resolved is not None else "needs_review",
                resolved=resolved if ready else None,
            )
        )
    return classified


__all__ = [
    "ConversionBulkRowClassification",
    "ReadinessKind",
    "classify_conversion_rows",
]
