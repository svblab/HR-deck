"""Репозиторий карточек сотрудников."""

from __future__ import annotations

import builtins
from dataclasses import dataclass

from data.db import Connection


@dataclass(frozen=True)
class EmployeeRecord:
    id: int
    external_id: str
    full_name: str
    position_id: int
    branch_id: int
    department_id: int | None
    division_id: int | None
    employment_type_id: int
    note: str | None
    hire_date: str | None
    contacts: str | None
    home_address: str | None
    social_insurance_number: str | None
    needs_org_review: bool
    is_archived: bool
    created_at: str
    updated_at: str


class EmployeeRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    _SELECT = (
        "SELECT id, external_id, full_name, position_id, branch_id, department_id, division_id,"
        " employment_type_id, note, hire_date, contacts, home_address,"
        " social_insurance_number, needs_org_review, is_archived, created_at, updated_at"
        " FROM employees"
    )

    def get(self, employee_id: int) -> EmployeeRecord | None:
        row = self._conn.execute(f"{self._SELECT} WHERE id = ?", (employee_id,)).fetchone()
        return _row(row) if row else None

    def get_by_external_id(self, external_id: str) -> EmployeeRecord | None:
        row = self._conn.execute(
            f"{self._SELECT} WHERE external_id = ?",
            (external_id,),
        ).fetchone()
        return _row(row) if row else None

    def list(self, *, active_only: bool = True) -> builtins.list[EmployeeRecord]:
        sql = self._SELECT
        if active_only:
            sql += " WHERE is_archived = 0"
        sql += " ORDER BY full_name, id"
        return [_row(r) for r in self._conn.execute(sql).fetchall()]

    def list_by_position(
        self, position_id: int, *, active_only: bool = True
    ) -> builtins.list[EmployeeRecord]:
        sql = f"{self._SELECT} WHERE position_id = ?"
        params: list[object] = [position_id]
        if active_only:
            sql += " AND is_archived = 0"
        sql += " ORDER BY full_name, id"
        return [_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def search_by_name(self, prefix: str, *, limit: int = 50) -> builtins.list[EmployeeRecord]:
        pattern = f"{prefix}%"
        rows = self._conn.execute(
            f"{self._SELECT} WHERE is_archived = 0 AND full_name LIKE ? "
            "ORDER BY full_name, id LIMIT ?",
            (pattern, limit),
        ).fetchall()
        return [_row(r) for r in rows]

    def create(
        self,
        *,
        external_id: str,
        full_name: str,
        position_id: int,
        branch_id: int,
        department_id: int | None,
        employment_type_id: int,
        created_at: str,
        division_id: int | None = None,
        note: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO employees ("
            " external_id, full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, note, hire_date, contacts, home_address,"
            " social_insurance_number, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 0, ?, ?)",
            (
                external_id,
                full_name,
                position_id,
                branch_id,
                department_id,
                division_id,
                employment_type_id,
                note,
                created_at,
                created_at,
            ),
        )
        return int(cur.lastrowid)

    def update(
        self,
        employee_id: int,
        *,
        full_name: str,
        position_id: int,
        branch_id: int,
        department_id: int | None,
        employment_type_id: int,
        updated_at: str,
        division_id: int | None = None,
        note: str | None = None,
    ) -> None:
        self._conn.execute(
            "UPDATE employees SET"
            " full_name = ?, position_id = ?, branch_id = ?, department_id = ?,"
            " division_id = ?, employment_type_id = ?, note = ?, updated_at = ?"
            " WHERE id = ?",
            (
                full_name,
                position_id,
                branch_id,
                department_id,
                division_id,
                employment_type_id,
                note,
                updated_at,
                employee_id,
            ),
        )

    def update_sensitive(
        self,
        employee_id: int,
        *,
        home_address: str | None,
        social_insurance_number: str | None,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            "UPDATE employees SET home_address = ?, social_insurance_number = ?,"
            " updated_at = ? WHERE id = ?",
            (home_address, social_insurance_number, updated_at, employee_id),
        )

    def set_archived(self, employee_id: int, *, archived: bool, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE employees SET is_archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, updated_at, employee_id),
        )

    def clear_org_assignment_for_review(
        self,
        employee_id: int,
        *,
        clear_department: bool,
        clear_division: bool,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            "UPDATE employees SET"
            " department_id = CASE WHEN ? THEN NULL ELSE department_id END,"
            " division_id = CASE WHEN ? THEN NULL ELSE division_id END,"
            " needs_org_review = 1, updated_at = ?"
            " WHERE id = ?",
            (
                int(clear_department),
                int(clear_division),
                updated_at,
                employee_id,
            ),
        )

    def clear_needs_org_review(self, employee_id: int, *, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE employees SET needs_org_review = 0, updated_at = ? WHERE id = ?",
            (updated_at, employee_id),
        )


def _row(row: tuple[object, ...]) -> EmployeeRecord:
    return EmployeeRecord(
        id=int(row[0]),
        external_id=str(row[1]),
        full_name=str(row[2]),
        position_id=int(row[3]),
        branch_id=int(row[4]),
        department_id=int(row[5]) if row[5] is not None else None,
        division_id=int(row[6]) if row[6] is not None else None,
        employment_type_id=int(row[7]),
        note=str(row[8]) if row[8] is not None else None,
        hire_date=str(row[9]) if row[9] is not None else None,
        contacts=str(row[10]) if row[10] is not None else None,
        home_address=str(row[11]) if row[11] is not None else None,
        social_insurance_number=str(row[12]) if row[12] is not None else None,
        needs_org_review=bool(int(row[13])),
        is_archived=bool(int(row[14])),
        created_at=str(row[15]),
        updated_at=str(row[16]),
    )
