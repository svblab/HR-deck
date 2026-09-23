"""Employee reconciliation table for directory-sync packages (ADR-0006 matching).

Classification is read-only here; persistence is ``EmployeeSyncImportService``.
"""

from __future__ import annotations

from collections.abc import Callable

from data.db import Connection
from data.directories import (
    DepartmentRecord,
    DepartmentRepository,
    DivisionRecord,
    DivisionRepository,
)
from data.employees import EmployeeRepository
from domain.directory_sync import DirectorySyncPackage
from domain.employee import normalize_name_for_match
from domain.employee_reconciliation import EmployeeMatchCandidate, EmployeeMatchStatus
from domain.permissions import Permission
from services.authorization import AuthorizationService
from services.session import SessionState

_OrgLookup = Callable[[str], DepartmentRecord | DivisionRecord | None]


class EmployeeReconciliationService:
    """Build a reconciliation table from package employee rows. Does not write."""

    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        authz: AuthorizationService | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._authz = authz or AuthorizationService()
        self._employees = EmployeeRepository(conn)
        self._departments = DepartmentRepository(conn)
        self._divisions = DivisionRepository(conn)

    def build_reconciliation(self, package: DirectorySyncPackage) -> list[EmployeeMatchCandidate]:
        self._require()
        results: list[EmployeeMatchCandidate] = []
        for row in package.tables.get("employees", []):
            results.append(self._classify(row))
        return results

    def _classify(self, row: dict[str, object]) -> EmployeeMatchCandidate:
        external_id = str(row["external_id"])
        local = self._employees.get_by_external_id(external_id)
        if local is not None:
            if normalize_name_for_match(local.full_name) == normalize_name_for_match(
                str(row["full_name"])
            ):
                return EmployeeMatchCandidate(row, EmployeeMatchStatus.EXACT, local.id)
            return EmployeeMatchCandidate(row, EmployeeMatchStatus.CONFLICT, local.id)
        candidates = self._find_name_candidates(row)
        if len(candidates) == 1:
            return EmployeeMatchCandidate(row, EmployeeMatchStatus.LOW, candidates[0])
        if len(candidates) > 1:
            return EmployeeMatchCandidate(
                row,
                EmployeeMatchStatus.AMBIGUOUS,
                None,
                candidate_employee_ids=tuple(candidates),
            )
        return EmployeeMatchCandidate(row, EmployeeMatchStatus.NEW, None)

    def _find_name_candidates(self, row: dict[str, object]) -> list[int]:
        """Name+org candidates, mirroring EmployeeImportService._duplicate_warnings.

        Package org refs are department_external_id / division_external_id.
        Resolve those to the local directory record (Part 4a get_by_external_id)
        and require the candidate's local department_id / division_id to be
        that record — not a same-named department in another branch.
        Unresolvable refs yield no candidates (new org unit not yet synced).
        """
        department_ok, department_id = self._resolve_org_id(
            self._departments.get_by_external_id, row.get("department_external_id")
        )
        division_ok, division_id = self._resolve_org_id(
            self._divisions.get_by_external_id, row.get("division_external_id")
        )
        if not department_ok or not division_ok:
            return []

        needle = normalize_name_for_match(str(row["full_name"]))
        # LIKE-search by the original string + scan of active cards: LIKE does
        # not treat «ё»/«е» as equivalent (ТЗ §3.7), same as import preview.
        by_id = {rec.id: rec for rec in self._employees.search_by_name(str(row["full_name"]))}
        for rec in self._employees.list(active_only=True):
            if rec.id in by_id:
                continue
            if normalize_name_for_match(rec.full_name) != needle:
                continue
            by_id[rec.id] = rec
        return sorted(
            rec.id
            for rec in by_id.values()
            if normalize_name_for_match(rec.full_name) == needle
            and rec.department_id == department_id
            and rec.division_id == division_id
        )

    @staticmethod
    def _resolve_org_id(getter: _OrgLookup, value: object) -> tuple[bool, int | None]:
        if value is None or value == "":
            return True, None
        record = getter(str(value))
        if record is None:
            return False, None
        return True, record.id

    def _require(self) -> None:
        # Same pair as EmployeeImportService.preview_*: HR review, not transport admin.
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.IMPORT_EXPORT)
        self._authz.require(self._session.role, Permission.MANAGE_EMPLOYEES)
