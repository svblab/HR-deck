"""Сырой экспорт списка сотрудников в XLSX (ТЗ §3.7, не отчёт EPIC-010)."""

from __future__ import annotations

from pathlib import Path

from domain.employee_import import EXPORT_HEADERS, SENSITIVE_EXPORT_HEADERS
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.directories import DirectoryService
from services.employee_files import write_xlsx
from services.employees import EmployeeService
from services.session import SessionState


class EmployeeExportService:
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

    def export_xlsx(self, path: Path) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)
        include_sensitive = self._authz.check(
            self._session.role, Permission.VIEW_SENSITIVE_EMPLOYEE_FIELDS
        )
        cards = self._employees.list_employees(active_only=True)
        names = self._names()
        headers = list(EXPORT_HEADERS)
        if include_sensitive:
            headers.extend(SENSITIVE_EXPORT_HEADERS)
        rows: list[list[str]] = []
        for card in cards:
            row = [
                card.full_name,
                names["positions"].get(card.position_id, ""),
                names["branches"].get(card.branch_id, ""),
                names["departments"].get(card.department_id, ""),
                names["divisions"].get(card.division_id, "")
                if card.division_id is not None
                else "",
                names["employment_types"].get(card.employment_type_id, ""),
            ]
            if include_sensitive:
                if card.sensitive_fields_masked:
                    row.extend(["", ""])
                else:
                    row.extend(
                        [card.home_address or "", card.social_insurance_number or ""]
                    )
            rows.append(row)
        write_xlsx(path, headers, rows)

    def _names(self) -> dict[str, dict[int, str]]:
        return {
            "positions": {
                r.id: r.name for r in self._directories.list_positions(active_only=False)
            },
            "branches": {
                r.id: r.name for r in self._directories.list_branches(active_only=False)
            },
            "departments": {
                r.id: r.name
                for r in self._directories.list_departments(active_only=False)
            },
            "divisions": {
                r.id: r.name for r in self._directories.list_divisions(active_only=False)
            },
            "employment_types": {
                r.id: r.name
                for r in self._directories.list_employment_types(active_only=False)
            },
        }
