"""Репозитории справочников оргструктуры (EPIC-004)."""

from __future__ import annotations

from dataclasses import dataclass

from data.db import Connection


@dataclass(frozen=True)
class BranchRecord:
    id: int
    external_id: str
    name: str
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DepartmentRecord:
    id: int
    external_id: str
    branch_id: int
    name: str
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DivisionRecord:
    id: int
    external_id: str
    branch_id: int
    department_id: int | None
    name: str
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PositionRecord:
    id: int
    external_id: str
    branch_id: int
    name: str
    department_required: bool
    division_required: bool
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EmploymentTypeRecord:
    id: int
    code: str
    name: str
    archives_record: bool
    is_archived: bool
    created_at: str
    updated_at: str


class BranchRepository:
    table = "branches"

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(self, *, active_only: bool = False) -> list[BranchRecord]:
        sql = (
            "SELECT id, external_id, name, is_archived, created_at, updated_at"
            " FROM branches"
        )
        if active_only:
            sql += " WHERE is_archived = 0"
        sql += " ORDER BY name"
        return [_branch_row(r) for r in self._conn.execute(sql).fetchall()]

    def get(self, branch_id: int) -> BranchRecord | None:
        row = self._conn.execute(
            "SELECT id, external_id, name, is_archived, created_at, updated_at"
            " FROM branches WHERE id = ?",
            (branch_id,),
        ).fetchone()
        return _branch_row(row) if row else None

    def get_by_external_id(self, external_id: str) -> BranchRecord | None:
        row = self._conn.execute(
            "SELECT id, external_id, name, is_archived, created_at, updated_at"
            " FROM branches WHERE external_id = ?",
            (external_id,),
        ).fetchone()
        return _branch_row(row) if row else None

    def create(self, *, external_id: str, name: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO branches (external_id, name, is_archived, created_at, updated_at)"
            " VALUES (?, ?, 0, ?, ?)",
            (external_id, name, created_at, created_at),
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
            "SELECT id, external_id, branch_id, name, is_archived, created_at, updated_at "
            f"FROM departments{where} ORDER BY name"
        )
        return [_department_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def get(self, department_id: int) -> DepartmentRecord | None:
        row = self._conn.execute(
            "SELECT id, external_id, branch_id, name, is_archived, created_at, updated_at "
            "FROM departments WHERE id = ?",
            (department_id,),
        ).fetchone()
        return _department_row(row) if row else None

    def get_by_external_id(self, external_id: str) -> DepartmentRecord | None:
        row = self._conn.execute(
            "SELECT id, external_id, branch_id, name, is_archived, created_at, updated_at "
            "FROM departments WHERE external_id = ?",
            (external_id,),
        ).fetchone()
        return _department_row(row) if row else None

    def create(self, *, external_id: str, branch_id: int, name: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO departments ("
            " external_id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?)",
            (external_id, branch_id, name, created_at, created_at),
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

    def set_branch(self, department_id: int, *, branch_id: int, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE departments SET branch_id = ?, updated_at = ? WHERE id = ?",
            (branch_id, updated_at, department_id),
        )


class DivisionRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(
        self,
        *,
        branch_id: int | None = None,
        department_id: int | None = None,
        active_only: bool = False,
    ) -> list[DivisionRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if branch_id is not None:
            clauses.append("branch_id = ?")
            params.append(branch_id)
        if department_id is not None:
            clauses.append("department_id = ?")
            params.append(department_id)
        if active_only:
            clauses.append("is_archived = 0")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, external_id, branch_id, department_id, name, is_archived,"
            f" created_at, updated_at FROM divisions{where} ORDER BY name"
        )
        return [_division_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def get(self, division_id: int) -> DivisionRecord | None:
        row = self._conn.execute(
            "SELECT id, external_id, branch_id, department_id, name, is_archived,"
            " created_at, updated_at FROM divisions WHERE id = ?",
            (division_id,),
        ).fetchone()
        return _division_row(row) if row else None

    def get_by_external_id(self, external_id: str) -> DivisionRecord | None:
        row = self._conn.execute(
            "SELECT id, external_id, branch_id, department_id, name, is_archived,"
            " created_at, updated_at FROM divisions WHERE external_id = ?",
            (external_id,),
        ).fetchone()
        return _division_row(row) if row else None

    def create(
        self,
        *,
        external_id: str,
        branch_id: int,
        department_id: int | None,
        name: str,
        created_at: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO divisions ("
            " external_id, branch_id, department_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, 0, ?, ?)",
            (external_id, branch_id, department_id, name, created_at, created_at),
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

    def set_parentage(
        self,
        division_id: int,
        *,
        branch_id: int,
        department_id: int | None,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            "UPDATE divisions SET branch_id = ?, department_id = ?, updated_at = ?"
            " WHERE id = ?",
            (branch_id, department_id, updated_at, division_id),
        )


class PositionRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(
        self,
        *,
        branch_id: int | None = None,
        active_only: bool = False,
    ) -> list[PositionRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if branch_id is not None:
            clauses.append("branch_id = ?")
            params.append(branch_id)
        if active_only:
            clauses.append("is_archived = 0")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, external_id, branch_id, name, department_required, division_required,"
            f" is_archived, created_at, updated_at FROM positions{where} ORDER BY name"
        )
        return [_position_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def get(self, position_id: int) -> PositionRecord | None:
        row = self._conn.execute(
            "SELECT id, external_id, branch_id, name, department_required, division_required,"
            " is_archived, created_at, updated_at FROM positions WHERE id = ?",
            (position_id,),
        ).fetchone()
        return _position_row(row) if row else None

    def get_by_external_id(self, external_id: str) -> PositionRecord | None:
        row = self._conn.execute(
            "SELECT id, external_id, branch_id, name, department_required, division_required,"
            " is_archived, created_at, updated_at FROM positions WHERE external_id = ?",
            (external_id,),
        ).fetchone()
        return _position_row(row) if row else None

    def create(
        self,
        *,
        external_id: str,
        branch_id: int,
        name: str,
        department_required: bool = False,
        division_required: bool = False,
        created_at: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO positions ("
            " external_id, branch_id, name, department_required, division_required,"
            " is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (
                external_id,
                branch_id,
                name,
                int(department_required),
                int(division_required),
                created_at,
                created_at,
            ),
        )
        return int(cur.lastrowid)

    def set_org_requirements(
        self,
        position_id: int,
        *,
        department_required: bool,
        division_required: bool,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            "UPDATE positions SET department_required = ?, division_required = ?,"
            " updated_at = ? WHERE id = ?",
            (int(department_required), int(division_required), updated_at, position_id),
        )

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

    def set_branch(self, position_id: int, *, branch_id: int, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE positions SET branch_id = ?, updated_at = ? WHERE id = ?",
            (branch_id, updated_at, position_id),
        )


class EmploymentTypeRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list(self, *, active_only: bool = False) -> list[EmploymentTypeRecord]:
        sql = (
            "SELECT id, code, name, archives_record, is_archived, created_at, updated_at"
            " FROM employment_types"
        )
        if active_only:
            sql += " WHERE is_archived = 0"
        sql += " ORDER BY name"
        return [_employment_type_row(r) for r in self._conn.execute(sql).fetchall()]

    def get(self, employment_type_id: int) -> EmploymentTypeRecord | None:
        row = self._conn.execute(
            "SELECT id, code, name, archives_record, is_archived, created_at, updated_at "
            "FROM employment_types WHERE id = ?",
            (employment_type_id,),
        ).fetchone()
        return _employment_type_row(row) if row else None

    def get_by_code(self, code: str) -> EmploymentTypeRecord | None:
        row = self._conn.execute(
            "SELECT id, code, name, archives_record, is_archived, created_at, updated_at "
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
        id=int(row[0]),
        external_id=str(row[1]),
        name=str(row[2]),
        is_archived=bool(int(row[3])),
        created_at=str(row[4]),
        updated_at=str(row[5]),
    )


def _department_row(row: tuple[object, ...]) -> DepartmentRecord:
    return DepartmentRecord(
        id=int(row[0]),
        external_id=str(row[1]),
        branch_id=int(row[2]),
        name=str(row[3]),
        is_archived=bool(int(row[4])),
        created_at=str(row[5]),
        updated_at=str(row[6]),
    )


def _division_row(row: tuple[object, ...]) -> DivisionRecord:
    return DivisionRecord(
        id=int(row[0]),
        external_id=str(row[1]),
        branch_id=int(row[2]),
        department_id=int(row[3]) if row[3] is not None else None,
        name=str(row[4]),
        is_archived=bool(int(row[5])),
        created_at=str(row[6]),
        updated_at=str(row[7]),
    )


def _position_row(row: tuple[object, ...]) -> PositionRecord:
    return PositionRecord(
        id=int(row[0]),
        external_id=str(row[1]),
        branch_id=int(row[2]),
        name=str(row[3]),
        department_required=bool(int(row[4])),
        division_required=bool(int(row[5])),
        is_archived=bool(int(row[6])),
        created_at=str(row[7]),
        updated_at=str(row[8]),
    )


def _employment_type_row(row: tuple[object, ...]) -> EmploymentTypeRecord:
    return EmploymentTypeRecord(
        id=int(row[0]),
        code=str(row[1]),
        name=str(row[2]),
        archives_record=bool(int(row[3])),
        is_archived=bool(int(row[4])),
        created_at=str(row[5]),
        updated_at=str(row[6]),
    )
