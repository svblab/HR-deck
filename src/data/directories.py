"""Репозитории справочников оргструктуры (EPIC-004)."""

from __future__ import annotations

from dataclasses import dataclass

from data.db import Connection


@dataclass(frozen=True)
class BranchRecord:
    id: int
    name: str
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DepartmentRecord:
    id: int
    branch_id: int
    name: str
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DivisionRecord:
    id: int
    department_id: int
    name: str
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PositionRecord:
    id: int
    name: str
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EmploymentTypeRecord:
    id: int
    code: str
    name: str
    is_archived: bool
    created_at: str
    updated_at: str


class BranchRepository:
    table = "branches"

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(self, *, active_only: bool = False) -> list[BranchRecord]:
        sql = "SELECT id, name, is_archived, created_at, updated_at FROM branches"
        if active_only:
            sql += " WHERE is_archived = 0"
        sql += " ORDER BY name"
        return [_branch_row(r) for r in self._conn.execute(sql).fetchall()]

    def get(self, branch_id: int) -> BranchRecord | None:
        row = self._conn.execute(
            "SELECT id, name, is_archived, created_at, updated_at FROM branches WHERE id = ?",
            (branch_id,),
        ).fetchone()
        return _branch_row(row) if row else None

    def create(self, *, name: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO branches (name, is_archived, created_at, updated_at) VALUES (?, 0, ?, ?)",
            (name, created_at, created_at),
        )
        return int(cur.lastrowid)

    def rename(self, branch_id: int, *, name: str, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE branches SET name = ?, updated_at = ? WHERE id = ?",
            (name, updated_at, branch_id),
        )

    def set_archived(self, branch_id: int, *, archived: bool, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE branches SET is_archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, updated_at, branch_id),
        )


class DepartmentRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(
        self,
        *,
        branch_id: int | None = None,
        active_only: bool = False,
    ) -> list[DepartmentRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if branch_id is not None:
            clauses.append("branch_id = ?")
            params.append(branch_id)
        if active_only:
            clauses.append("is_archived = 0")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, branch_id, name, is_archived, created_at, updated_at "
            f"FROM departments{where} ORDER BY name"
        )
        return [_department_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def get(self, department_id: int) -> DepartmentRecord | None:
        row = self._conn.execute(
            "SELECT id, branch_id, name, is_archived, created_at, updated_at "
            "FROM departments WHERE id = ?",
            (department_id,),
        ).fetchone()
        return _department_row(row) if row else None

    def create(self, *, branch_id: int, name: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO departments (branch_id, name, is_archived, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (branch_id, name, created_at, created_at),
        )
        return int(cur.lastrowid)

    def rename(self, department_id: int, *, name: str, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE departments SET name = ?, updated_at = ? WHERE id = ?",
            (name, updated_at, department_id),
        )

    def set_archived(self, department_id: int, *, archived: bool, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE departments SET is_archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, updated_at, department_id),
        )


class DivisionRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(
        self,
        *,
        department_id: int | None = None,
        active_only: bool = False,
    ) -> list[DivisionRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if department_id is not None:
            clauses.append("department_id = ?")
            params.append(department_id)
        if active_only:
            clauses.append("is_archived = 0")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, department_id, name, is_archived, created_at, updated_at "
            f"FROM divisions{where} ORDER BY name"
        )
        return [_division_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def get(self, division_id: int) -> DivisionRecord | None:
        row = self._conn.execute(
            "SELECT id, department_id, name, is_archived, created_at, updated_at "
            "FROM divisions WHERE id = ?",
            (division_id,),
        ).fetchone()
        return _division_row(row) if row else None

    def create(self, *, department_id: int, name: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO divisions (department_id, name, is_archived, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (department_id, name, created_at, created_at),
        )
        return int(cur.lastrowid)

    def rename(self, division_id: int, *, name: str, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE divisions SET name = ?, updated_at = ? WHERE id = ?",
            (name, updated_at, division_id),
        )

    def set_archived(self, division_id: int, *, archived: bool, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE divisions SET is_archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, updated_at, division_id),
        )


class PositionRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(self, *, active_only: bool = False) -> list[PositionRecord]:
        sql = "SELECT id, name, is_archived, created_at, updated_at FROM positions"
        if active_only:
            sql += " WHERE is_archived = 0"
        sql += " ORDER BY name"
        return [_position_row(r) for r in self._conn.execute(sql).fetchall()]

    def get(self, position_id: int) -> PositionRecord | None:
        row = self._conn.execute(
            "SELECT id, name, is_archived, created_at, updated_at FROM positions WHERE id = ?",
            (position_id,),
        ).fetchone()
        return _position_row(row) if row else None

    def create(self, *, name: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO positions (name, is_archived, created_at, updated_at) VALUES (?, 0, ?, ?)",
            (name, created_at, created_at),
        )
        return int(cur.lastrowid)

    def rename(self, position_id: int, *, name: str, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE positions SET name = ?, updated_at = ? WHERE id = ?",
            (name, updated_at, position_id),
        )

    def set_archived(self, position_id: int, *, archived: bool, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE positions SET is_archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, updated_at, position_id),
        )


class EmploymentTypeRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(self, *, active_only: bool = False) -> list[EmploymentTypeRecord]:
        sql = "SELECT id, code, name, is_archived, created_at, updated_at FROM employment_types"
        if active_only:
            sql += " WHERE is_archived = 0"
        sql += " ORDER BY name"
        return [_employment_type_row(r) for r in self._conn.execute(sql).fetchall()]

    def get(self, employment_type_id: int) -> EmploymentTypeRecord | None:
        row = self._conn.execute(
            "SELECT id, code, name, is_archived, created_at, updated_at "
            "FROM employment_types WHERE id = ?",
            (employment_type_id,),
        ).fetchone()
        return _employment_type_row(row) if row else None

    def get_by_code(self, code: str) -> EmploymentTypeRecord | None:
        row = self._conn.execute(
            "SELECT id, code, name, is_archived, created_at, updated_at "
            "FROM employment_types WHERE code = ?",
            (code,),
        ).fetchone()
        return _employment_type_row(row) if row else None

    def create(self, *, code: str, name: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO employment_types (code, name, is_archived, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (code, name, created_at, created_at),
        )
        return int(cur.lastrowid)

    def rename(self, employment_type_id: int, *, name: str, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE employment_types SET name = ?, updated_at = ? WHERE id = ?",
            (name, updated_at, employment_type_id),
        )

    def set_archived(self, employment_type_id: int, *, archived: bool, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE employment_types SET is_archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, updated_at, employment_type_id),
        )


def _branch_row(row: tuple[object, ...]) -> BranchRecord:
    return BranchRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        name=str(row[1]),
        is_archived=bool(int(row[2])),  # type: ignore[arg-type]
        created_at=str(row[3]),
        updated_at=str(row[4]),
    )


def _department_row(row: tuple[object, ...]) -> DepartmentRecord:
    return DepartmentRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        branch_id=int(row[1]),  # type: ignore[arg-type]
        name=str(row[2]),
        is_archived=bool(int(row[3])),  # type: ignore[arg-type]
        created_at=str(row[4]),
        updated_at=str(row[5]),
    )


def _division_row(row: tuple[object, ...]) -> DivisionRecord:
    return DivisionRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        department_id=int(row[1]),  # type: ignore[arg-type]
        name=str(row[2]),
        is_archived=bool(int(row[3])),  # type: ignore[arg-type]
        created_at=str(row[4]),
        updated_at=str(row[5]),
    )


def _position_row(row: tuple[object, ...]) -> PositionRecord:
    return PositionRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        name=str(row[1]),
        is_archived=bool(int(row[2])),  # type: ignore[arg-type]
        created_at=str(row[3]),
        updated_at=str(row[4]),
    )


def _employment_type_row(row: tuple[object, ...]) -> EmploymentTypeRecord:
    return EmploymentTypeRecord(
        id=int(row[0]),  # type: ignore[arg-type]
        code=str(row[1]),
        name=str(row[2]),
        is_archived=bool(int(row[3])),  # type: ignore[arg-type]
        created_at=str(row[4]),
        updated_at=str(row[5]),
    )
