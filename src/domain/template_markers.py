"""Каталог маркеров и разбор {{…}} по ADR-0005 (contract 1.0)."""

from __future__ import annotations

import re
from dataclasses import dataclass

CONTRACT_VERSION = "1.0"

MARKER_RE = re.compile(r"\{\{([^{}]+)\}\}")
BLOCK_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# canonical key -> aliases (ADR-0005 table)
_ALIASES: dict[str, tuple[str, ...]] = {
    "report.title": ("заголовок",),
    "report.date": ("дата",),
    "report.period_from": ("период_с",),
    "report.period_to": ("период_по",),
    "employee.full_name": ("ФИО",),
    "employee.position": ("должность",),
    "employee.branch": ("филиал",),
    "employee.department": ("департамент",),
    "employee.division": ("отдел",),
    "employee.status": ("статус",),
    "employee.status_from": ("статус_с",),
    "employee.status_to": ("статус_по",),
    "employee.employment_type": ("тип_занятости",),
}

CANONICAL_KEYS: frozenset[str] = frozenset(_ALIASES)

_TOKEN_TO_CANONICAL: dict[str, str] = {}
for _key, _names in _ALIASES.items():
    _TOKEN_TO_CANONICAL[_key] = _key
    for _alias in _names:
        _TOKEN_TO_CANONICAL[_alias] = _key


class MarkerSyntaxError(ValueError):
    """Некорректный синтаксис маркера (пробелы, вложенность)."""


@dataclass(frozen=True)
class RowBlockSpec:
    name: str | None
    start_row: int
    end_row: int


def extract_markers(text: str) -> list[str]:
    if text is None or not isinstance(text, str):
        return []
    found: list[str] = []
    for match in MARKER_RE.finditer(text):
        token = match.group(1)
        if " " in token or "\t" in token:
            raise MarkerSyntaxError(f"spaces inside marker: {{{{{token}}}}}")
        found.append(token)
    return found


def is_structural_token(token: str) -> bool:
    return token in {"#ROW", "/ROW"} or token.startswith("#ROW:") or token.startswith("/ROW:")


def canonical_key(token: str) -> str | None:
    if is_structural_token(token):
        return None
    return _TOKEN_TO_CANONICAL.get(token)


def block_name_from_token(token: str) -> str | None:
    if token.startswith("#ROW:"):
        return token[5:]
    if token.startswith("/ROW:"):
        return token[5:]
    return None


def validate_block_name(name: str) -> bool:
    return bool(BLOCK_NAME_RE.match(name))
