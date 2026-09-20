"""Unit: семантика типов занятости (ADR-0011)."""

from __future__ import annotations

from dataclasses import dataclass

from domain.employment_types import (
    DEFAULT_ARCHIVING_EMPLOYMENT_CODE,
    resolve_default_archiving_type,
)


@dataclass(frozen=True)
class _Type:
    code: str
    archives_record: bool
    is_archived: bool = False


def test_resolve_prefers_dismissed_among_archiving_types() -> None:
    types = [
        _Type("contract_ended", True),
        _Type(DEFAULT_ARCHIVING_EMPLOYMENT_CODE, True),
        _Type("retired", True),
    ]
    chosen = resolve_default_archiving_type(types)
    assert chosen is not None
    assert chosen.code == DEFAULT_ARCHIVING_EMPLOYMENT_CODE


def test_resolve_lowest_code_when_dismissed_absent() -> None:
    types = [_Type("retired", True), _Type("contract_ended", True)]
    chosen = resolve_default_archiving_type(types)
    assert chosen is not None
    assert chosen.code == "contract_ended"


def test_resolve_none_when_no_archiving_types() -> None:
    types = [_Type("staff", False), _Type("temporary", False)]
    assert resolve_default_archiving_type(types) is None


def test_resolve_skips_archived_directory_entries_when_active_only() -> None:
    types = [
        _Type(DEFAULT_ARCHIVING_EMPLOYMENT_CODE, True, is_archived=True),
        _Type("retired", True),
    ]
    chosen = resolve_default_archiving_type(types, active_only=True)
    assert chosen is not None
    assert chosen.code == "retired"
