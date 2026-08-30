"""Репозиторий библиотеки шаблонов отчётов (EPIC-011 Step 3)."""

from __future__ import annotations

from dataclasses import dataclass

from data.db import Connection


@dataclass(frozen=True)
class TemplateRecord:
    id: int
    name: str
    format: str
    is_archived: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TemplateVersionRecord:
    id: int
    template_id: int
    version_number: int
    stored_path: str
    contract_version: str
    binding_mode: str
    manifest_path: str | None
    created_at: str
    created_by_account_id: int | None


@dataclass(frozen=True)
class GeneratedReportRecord:
    id: int
    template_version_id: int
    output_path: str
    generated_at: str
    generated_by_account_id: int | None


class ReportTemplateRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create_template(self, *, name: str, fmt: str, created_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO report_templates (name, format, is_archived, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (name, fmt, created_at, created_at),
        )
        return int(cur.lastrowid)

    def get_template(self, template_id: int) -> TemplateRecord | None:
        row = self._conn.execute(
            "SELECT id, name, format, is_archived, created_at, updated_at "
            "FROM report_templates WHERE id = ?",
            (template_id,),
        ).fetchone()
        return _template_row(row) if row else None

    def list_templates(self, *, active_only: bool = False) -> list[TemplateRecord]:
        sql = (
            "SELECT id, name, format, is_archived, created_at, updated_at "
            "FROM report_templates"
        )
        params: list[object] = []
        if active_only:
            sql += " WHERE is_archived = 0"
        sql += " ORDER BY name, id"
        return [_template_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def set_archived(self, template_id: int, *, archived: bool, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE report_templates SET is_archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, updated_at, template_id),
        )

    def next_version_number(self, template_id: int) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) FROM report_template_versions "
            "WHERE template_id = ?",
            (template_id,),
        ).fetchone()
        return int(row[0]) + 1

    def add_version(
        self,
        *,
        template_id: int,
        version_number: int,
        stored_path: str,
        contract_version: str,
        binding_mode: str,
        manifest_path: str | None,
        created_at: str,
        created_by_account_id: int | None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO report_template_versions ("
            " template_id, version_number, stored_path, contract_version, binding_mode,"
            " manifest_path, created_at, created_by_account_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                template_id,
                version_number,
                stored_path,
                contract_version,
                binding_mode,
                manifest_path,
                created_at,
                created_by_account_id,
            ),
        )
        return int(cur.lastrowid)

    def get_version(self, version_id: int) -> TemplateVersionRecord | None:
        row = self._conn.execute(
            "SELECT id, template_id, version_number, stored_path, contract_version,"
            " binding_mode, manifest_path, created_at, created_by_account_id "
            "FROM report_template_versions WHERE id = ?",
            (version_id,),
        ).fetchone()
        return _version_row(row) if row else None

    def list_versions(self, template_id: int) -> list[TemplateVersionRecord]:
        rows = self._conn.execute(
            "SELECT id, template_id, version_number, stored_path, contract_version,"
            " binding_mode, manifest_path, created_at, created_by_account_id "
            "FROM report_template_versions WHERE template_id = ? ORDER BY version_number",
            (template_id,),
        ).fetchall()
        return [_version_row(r) for r in rows]

    def record_generated(
        self,
        *,
        template_version_id: int,
        output_path: str,
        generated_at: str,
        generated_by_account_id: int | None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO template_generated_reports ("
            " template_version_id, output_path, generated_at, generated_by_account_id"
            ") VALUES (?, ?, ?, ?)",
            (template_version_id, output_path, generated_at, generated_by_account_id),
        )
        return int(cur.lastrowid)

    def get_generated(self, generated_id: int) -> GeneratedReportRecord | None:
        row = self._conn.execute(
            "SELECT id, template_version_id, output_path, generated_at, generated_by_account_id "
            "FROM template_generated_reports WHERE id = ?",
            (generated_id,),
        ).fetchone()
        return _generated_row(row) if row else None


def _template_row(row: tuple[object, ...]) -> TemplateRecord:
    return TemplateRecord(
        id=int(row[0]),
        name=str(row[1]),
        format=str(row[2]),
        is_archived=bool(int(row[3])),
        created_at=str(row[4]),
        updated_at=str(row[5]),
    )


def _version_row(row: tuple[object, ...]) -> TemplateVersionRecord:
    return TemplateVersionRecord(
        id=int(row[0]),
        template_id=int(row[1]),
        version_number=int(row[2]),
        stored_path=str(row[3]),
        contract_version=str(row[4]),
        binding_mode=str(row[5]),
        manifest_path=None if row[6] is None else str(row[6]),
        created_at=str(row[7]),
        created_by_account_id=None if row[8] is None else int(row[8]),
    )


def _generated_row(row: tuple[object, ...]) -> GeneratedReportRecord:
    return GeneratedReportRecord(
        id=int(row[0]),
        template_version_id=int(row[1]),
        output_path=str(row[2]),
        generated_at=str(row[3]),
        generated_by_account_id=None if row[4] is None else int(row[4]),
    )
