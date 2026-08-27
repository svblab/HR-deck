"""Предпросмотр и подтверждение импорта сотрудников (ТЗ §3.7)."""

from __future__ import annotations

from pathlib import Path

from domain.employee import EmployeeCreateInput, format_search_hit_label
from domain.employee_import import (
    ImportCatalog,
    ImportIssue,
    ImportPreview,
    ImportReadyRow,
    evaluate_row,
    map_headers,
    missing_required_headers,
)
from domain.permissions import Permission
from services.authorization import AuthorizationError, AuthorizationService
from services.directories import DirectoryService
from services.employee_files import EmployeeFileError, read_tabular
from services.employees import EmployeeService
from services.session import SessionState


class EmployeeImportError(Exception):
    """Ошибка чтения файла или прав на импорт."""


class EmployeeImportService:
    def __init__(
        self,
        employees: EmployeeService,
        directories: DirectoryService,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
    ) -> None:
        self._employees = employees
        self._directories = directories
        self._session = session
        self._authz = authz or AuthorizationService()

    def preview_path(self, path: Path) -> ImportPreview:
        self._require()
        try:
            headers, rows = read_tabular(path)
        except EmployeeFileError as exc:
            raise EmployeeImportError(str(exc)) from exc
        return self.preview_rows(headers, rows)

    def preview_rows(self, headers: list[str], rows: list[list[str]]) -> ImportPreview:
        self._require()
        mapping = map_headers(headers)
        missing = missing_required_headers(mapping)
        if missing:
            msg = "missing columns: " + ", ".join(missing)
            return ImportPreview(ready=(), errors=(ImportIssue(0, msg),), warnings=())
        catalog = self._catalog()
        ready: list[ImportReadyRow] = []
        errors: list[ImportIssue] = []
        warnings: list[ImportIssue] = []
        for offset, row in enumerate(rows, start=2):
            if not any(cell.strip() for cell in row):
                continue
            values = {
                key: row[idx] if idx < len(row) else "" for key, idx in mapping.items()
            }
            payload, issues = evaluate_row(values, offset, catalog)
            blocking = [i for i in issues if i.blocking]
            if blocking or payload is None:
                errors.extend(blocking or issues)
                continue
            dup_warnings = self._duplicate_warnings(payload, values, offset)
            warnings.extend(dup_warnings)
            ready.append(
                ImportReadyRow(
                    source_row=offset,
                    payload=payload,
                    warnings=tuple(w.message for w in dup_warnings),
                )
            )
        return ImportPreview(
            ready=tuple(ready), errors=tuple(errors), warnings=tuple(warnings)
        )

    def confirm(self, preview: ImportPreview) -> list[int]:
        self._require()
        created: list[int] = []
        for row in preview.ready:
            created.append(self._employees.create_employee(row.payload))
        return created

    def _duplicate_warnings(
        self, payload: EmployeeCreateInput, values: dict[str, str], source_row: int
    ) -> list[ImportIssue]:
        hits = self._employees.search_by_name(payload.full_name)
        dept = values["department"].strip().casefold()
        div = values["division"].strip().casefold()
        matches = [
            hit
            for hit in hits
            if hit.full_name.strip().casefold() == payload.full_name.casefold()
            and hit.department_name.strip().casefold() == dept
            and (hit.division_name or "").strip().casefold() == div
        ]
        if not matches:
            return []
        labels = "; ".join(format_search_hit_label(hit) for hit in matches[:5])
        return [
            ImportIssue(
                source_row,
                f"possible duplicate (name + subdivision): {labels}",
                blocking=False,
            )
        ]

    def _catalog(self) -> ImportCatalog:
        def index(items: list) -> dict[str, int]:
            out: dict[str, int] = {}
            dupes: set[str] = set()
            for item in items:
                key = item.name.strip().casefold()
                if key in out:
                    dupes.add(key)
                else:
                    out[key] = item.id
            for key in dupes:
                del out[key]
            return out

        positions = index(self._directories.list_positions(active_only=True))
        branches = index(self._directories.list_branches(active_only=True))
        employment = index(self._directories.list_employment_types(active_only=True))
        for item in self._directories.list_employment_types(active_only=True):
            employment.setdefault(item.code.strip().casefold(), item.id)
        departments: dict[tuple[int, str], int] = {}
        for dept in self._directories.list_departments(active_only=True):
            departments[(dept.branch_id, dept.name.strip().casefold())] = dept.id
        divisions: dict[tuple[int, str], int] = {}
        for div in self._directories.list_divisions(active_only=True):
            divisions[(div.department_id, div.name.strip().casefold())] = div.id
        return ImportCatalog(
            positions=positions,
            branches=branches,
            departments=departments,
            divisions=divisions,
            employment_types=employment,
        )

    def _require(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)
        self._authz.require(self._session.role, Permission.MANAGE_EMPLOYEES)


__all__ = ["AuthorizationError", "EmployeeImportError", "EmployeeImportService"]
