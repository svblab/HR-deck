"""EPIC-018: постановка строк в очередь конвертации из таблицы (ADR-0012)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from domain.employee_import import cell_text, map_headers


def file_content_hash(raw_bytes: bytes) -> str:
    """SHA-256 hex digest of raw source file bytes."""
    return hashlib.sha256(raw_bytes).hexdigest()


def build_staged_row_values(
    headers: list[str], rows: list[list[str]]
) -> list[tuple[int, dict[str, str]]]:
    """
    Map headers via HEADER_TO_KEY, keep only mapped columns.

    Source row numbers follow EmployeeImportService convention: first data row is 2.
    Rows without non-empty full_name are omitted.
    """
    mapping = map_headers(headers)
    if not mapping:
        return []
    staged: list[tuple[int, dict[str, str]]] = []
    for source_row_number, row in enumerate(rows, start=2):
        if not any(str(cell).strip() for cell in row):
            continue
        values = {
            key: cell_text(row[idx] if idx < len(row) else "")
            for key, idx in mapping.items()
        }
        if not values.get("full_name", "").strip():
            continue
        staged.append((source_row_number, values))
    return staged


def stale_cutoff(now_iso: str, *, days: int = 30) -> str:
    """ISO-8601 'Z' timestamp `days` before `now_iso`, same format as last_accessed_at."""
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    cutoff = now - timedelta(days=days)
    return cutoff.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = ["build_staged_row_values", "file_content_hash", "stale_cutoff"]
