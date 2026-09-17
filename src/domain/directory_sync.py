"""Directory sync package content model (ADR-0010 Part 3)."""

from __future__ import annotations

from dataclasses import dataclass

# Tables that participate in branch-scoped directory sync packages.
# employment_types and availability_statuses are deliberately excluded (ADR-0010).
SYNCED_TABLES = ("branches", "departments", "divisions", "positions", "employees")


@dataclass(frozen=True)
class DirectorySyncPackage:
    """Plaintext payload of whole-table dumps keyed by table name.

    Only tables with at least one row newer than the direction watermark are
    present; each included table carries *all* of its current rows.
    """

    tables: dict[str, list[dict[str, object]]]

    def is_empty(self) -> bool:
        return not self.tables
