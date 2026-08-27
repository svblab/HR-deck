"""Разбор и проверка строк импорта сотрудников (ТЗ §3.7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from domain.employee import EmployeeCreateInput, EmployeeValidationError, clean_full_name

REQUIRED_KEYS = (
    "full_name",
    "position",
    "branch",
    "department",
    "division",
    "employment_type",
)

HEADER_TO_KEY: dict[str, str] = {
    "фио": "full_name",
    "должность": "position",
    "филиал": "branch",
    "департамент": "department",
    "отдел": "division",
    "тип занятости": "employment_type",
    "дата приёма": "hire_date",
    "дата приема": "hire_date",
    "домашний адрес": "home_address",
    "номер страхования": "social_insurance_number",
}

EXPORT_HEADERS = (
    "ФИО",
    "Должность",
    "Филиал",
    "Департамент",
    "Отдел",
    "Тип занятости",
)
SENSITIVE_EXPORT_HEADERS = ("Домашний адрес", "Номер страхования")


@dataclass(frozen=True)
class ImportCatalog:
    """Справочники, уже полученные через DirectoryService (имена — casefold)."""

    positions: dict[str, int]
    branches: dict[str, int]
    departments: dict[tuple[int, str], int]
    divisions: dict[tuple[int, str], int]
    employment_types: dict[str, int]


@dataclass(frozen=True)
class ImportIssue:
    source_row: int
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class ImportReadyRow:
    source_row: int
    payload: EmployeeCreateInput
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ImportPreview:
    ready: tuple[ImportReadyRow, ...]
    errors: tuple[ImportIssue, ...]
    warnings: tuple[ImportIssue, ...]


def header_key(label: str) -> str | None:
    return HEADER_TO_KEY.get(label.strip().casefold())


def map_headers(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(headers):
        key = header_key(raw)
        if key is not None:
            mapping[key] = idx
    return mapping


def missing_required_headers(mapping: dict[str, int]) -> list[str]:
    return [key for key in REQUIRED_KEYS if key not in mapping]


def parse_hire_date(raw: str) -> str | None:
    clean = raw.strip()
    if not clean:
        return None
    try:
        return datetime.strptime(clean, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise EmployeeValidationError("hire_date must be YYYY-MM-DD") from exc


def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _lookup(index: dict[str, int], raw: str, label: str) -> int:
    key = raw.strip().casefold()
    if not key:
        raise EmployeeValidationError(f"{label} is required")
    found = index.get(key)
    if found is None:
        raise EmployeeValidationError(f"unknown {label}: {raw.strip()}")
    return found


def evaluate_row(
    values: dict[str, str], source_row: int, catalog: ImportCatalog
) -> tuple[EmployeeCreateInput | None, list[ImportIssue]]:
    issues: list[ImportIssue] = []
    for key in REQUIRED_KEYS:
        if not values.get(key, "").strip():
            issues.append(ImportIssue(source_row, f"{key} is required"))
    hire_raw = values.get("hire_date", "")
    if hire_raw.strip():
        try:
            parse_hire_date(hire_raw)
        except EmployeeValidationError as exc:
            issues.append(ImportIssue(source_row, str(exc)))
    if issues:
        return None, issues
    try:
        full_name = clean_full_name(values["full_name"])
        position_id = _lookup(catalog.positions, values["position"], "position")
        branch_id = _lookup(catalog.branches, values["branch"], "branch")
        department_id = catalog.departments.get(
            (branch_id, values["department"].strip().casefold())
        )
        if department_id is None:
            raise EmployeeValidationError(
                f"unknown department: {values['department'].strip()}"
            )
        division_id = catalog.divisions.get(
            (department_id, values["division"].strip().casefold())
        )
        if division_id is None:
            raise EmployeeValidationError(
                f"unknown division: {values['division'].strip()}"
            )
        employment_type_id = _lookup(
            catalog.employment_types, values["employment_type"], "employment_type"
        )
    except EmployeeValidationError as exc:
        return None, [ImportIssue(source_row, str(exc))]
    payload = EmployeeCreateInput(
        full_name=full_name,
        position_id=position_id,
        branch_id=branch_id,
        department_id=department_id,
        employment_type_id=employment_type_id,
        division_id=division_id,
    )
    return payload, []
