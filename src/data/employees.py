"""Репозиторий карточек сотрудников."""

from __future__ import annotations

from dataclasses import dataclass

from data.db import Connection


@dataclass(frozen=True)
class EmployeeRecord:
    id: int
    full_name: str
    position_id: int
    branch_id: int
    department_id: int
    division_id: int | None
    employment_type_id: int
    note: str | None
    hire_date: str | None
    contacts: str | None
    home_address: str | None
    social_insurance_number: str | None
    is_archived: bool
    created_at: str
    updated_at: str


class EmployeeRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    _SELECT = (
        "SELECT id, full_name, position_id, branch_id, department_id, division_id,"
        " employment_type_id, note, hire_date, contacts, home_address,"
        " social_insurance_number, is_archived, created_at, updated_at"
        " FROM employees"
    )

    def get(self, employee_id: int) -> EmployeeRecord | None:
        row = self._conn.execute(f"{self._SELECT} WHERE id = ?", (employee_id,)).fetchone()
        return _row(row) if row else None

    def list(self, *, active_only: bool = True) -> list[EmployeeRecord]:
        sql = self._SELECT
        if active_only:
            sql += " WHERE is_archived = 0"
        sql += " ORDER BY full_name, id"
        return [_row(r) for r in self._conn.execute(sql).fetchall()]

    def search_by_name(self, prefix: str, *, limit: int = 50) -> list[EmployeeRecord]:
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
        full_name: str,
        position_id: int,
        branch_id: int,
        department_id: int,
        employment_type_id: int,
        created_at: str,
        division_id: int | None = None,
        note: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO employees ("
            " full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, note, hire_date, contacts, home_address,"
            " social_insurance_number, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 0, ?, ?)",
            (
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
        department_id: int,
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


def _row(row: tuple[object, ...]) -> EmployeeRecord:
    return EmployeeRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        full_name=str(row[1]),
        position_id=int(row[2]),  # type: ignore[arg-type]
        branch_id=int(row[3]),  # type: ignore[arg-type]
        department_id=int(row[4]),  # type: ignore[arg-type]
        division_id=int(row[5]) if row[5] is not None else None,  # type: ignore[arg-type]
        employment_type_id=int(row[6]),  # type: ignore[arg-type]
        note=str(row[7]) if row[7] is not None else None,
        hire_date=str(row[8]) if row[8] is not None else None,
        contacts=str(row[9]) if row[9] is not None else None,
        home_address=str(row[10]) if row[10] is not None else None,
        social_insurance_number=str(row[11]) if row[11] is not None else None,
        is_archived=bool(int(row[12])),  # type: ignore[arg-type]
        created_at=str(row[13]),
        updated_at=str(row[14]),
    )
