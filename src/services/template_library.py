"""Библиотека шаблонов: версии, архив, генерация (EPIC-011 Step 3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from data.db import Connection
from data.paths import templates_storage_dir
from data.report_templates import (
    GeneratedReportRecord,
    ReportTemplateRepository,
    TemplateRecord,
    TemplateVersionRecord,
)
from data.repositories import UserActionLogRepository
from domain.action_log import ENTITY_TEMPLATE
from domain.permissions import Permission
from reports.excel_template import ArchivedTemplate, archive_upload, generate_excel_report
from reports.pdf_template import ArchivedPdfTemplate, archive_pdf_upload, generate_pdf_report
from services.authorization import AuthorizationError, AuthorizationService
from services.session import SessionState

Clock = Callable[[], str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class TemplateLibraryError(Exception):
    """Ошибка библиотеки шаблонов."""


@dataclass(frozen=True)
class TemplateView:
    id: int
    name: str
    format: str
    is_archived: bool
    latest_version: int | None


@dataclass(frozen=True)
class TemplateVersionView:
    id: int
    template_id: int
    version_number: int
    binding_mode: str
    contract_version: str


class TemplateLibraryService:
    def __init__(
        self,
        conn: Connection,
        session: SessionState,
        *,
        data_dir: Path | None = None,
        authz: AuthorizationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn = conn
        self._session = session
        self._storage_root = templates_storage_dir(data_dir)
        self._authz = authz or AuthorizationService()
        self._clock: Clock = clock or _utc_now
        self._repo = ReportTemplateRepository(conn)
        self._audit = UserActionLogRepository(conn)

    def list_templates(self, *, active_only: bool = False) -> list[TemplateView]:
        self._require_use()
        templates = self._repo.list_templates(active_only=active_only)
        return [self._to_view(t) for t in templates]

    def list_versions(self, template_id: int) -> list[TemplateVersionView]:
        self._require_use()
        return [self._to_version_view(v) for v in self._repo.list_versions(template_id)]

    def upload_version(
        self,
        *,
        name: str,
        source: Path,
        template_id: int | None = None,
        manifest_source: Path | None = None,
    ) -> int:
        self._require_manage()
        now = self._clock()
        try:
            fmt = _detect_format(source)
            if template_id is None:
                template_id = self._repo.create_template(
                    name=name.strip(), fmt=fmt, created_at=now
                )
            else:
                existing = self._repo.get_template(template_id)
                if existing is None:
                    raise TemplateLibraryError("template not found")
                if existing.format != fmt:
                    raise TemplateLibraryError("template format mismatch")

            version_number = self._repo.next_version_number(template_id)
            version_dir = self._storage_root / str(template_id) / f"v{version_number}"
            version_dir.mkdir(parents=True, exist_ok=True)
            stored = version_dir / _stored_name(fmt)

            if fmt == "excel":
                archived = archive_upload(source, stored)
                binding = "excel"
                manifest_path: str | None = None
                contract = archived.contract_version
            else:
                archived = archive_pdf_upload(
                    source,
                    stored,
                    manifest_source=manifest_source,
                )
                manifest_path = (
                    str(archived.manifest_path) if archived.manifest_path is not None else None
                )
                binding = archived.binding
                contract = archived.contract_version

            version_id = self._repo.add_version(
                template_id=template_id,
                version_number=version_number,
                stored_path=str(stored),
                contract_version=contract,
                binding_mode=binding,
                manifest_path=manifest_path,
                created_at=now,
                created_by_account_id=self._session.account_id,
            )
            self._record_audit(
                action_type="template.upload",
                entity_id=template_id,
                created_at=now,
                details=f"version={version_number};binding={binding}",
            )
            self._conn.commit()
            return version_id
        except Exception:
            self._conn.rollback()
            raise

    def archive_template(self, template_id: int) -> None:
        self._require_manage()
        if self._repo.get_template(template_id) is None:
            raise TemplateLibraryError("template not found")
        now = self._clock()
        try:
            self._repo.set_archived(template_id, archived=True, updated_at=now)
            self._record_audit(
                action_type="template.archive",
                entity_id=template_id,
                created_at=now,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def restore_template(self, template_id: int) -> None:
        self._require_manage()
        if self._repo.get_template(template_id) is None:
            raise TemplateLibraryError("template not found")
        now = self._clock()
        try:
            self._repo.set_archived(template_id, archived=False, updated_at=now)
            self._record_audit(
                action_type="template.restore",
                entity_id=template_id,
                created_at=now,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def generate_report(
        self,
        version_id: int,
        output_path: Path,
        *,
        values: dict[str, str],
        row_records: list[dict[str, str]] | None = None,
    ) -> GeneratedReportRecord:
        self._require_use()
        version = self._require_version(version_id)
        template = self._repo.get_template(version.template_id)
        if template is None:
            raise TemplateLibraryError("template not found")
        if template.is_archived:
            raise TemplateLibraryError("template is archived")

        now = self._clock()
        try:
            if template.format == "excel":
                generate_excel_report(
                    ArchivedTemplate(archive_path=Path(version.stored_path)),
                    output_path,
                    scalars=values,
                    row_records=row_records,
                )
            else:
                manifest = Path(version.manifest_path) if version.manifest_path else None
                generate_pdf_report(
                    ArchivedPdfTemplate(
                        archive_path=Path(version.stored_path),
                        binding=version.binding_mode,  # type: ignore[arg-type]
                        manifest_path=manifest,
                        contract_version=version.contract_version,
                    ),
                    output_path,
                    values,
                )

            generated_id = self._repo.record_generated(
                template_version_id=version_id,
                output_path=str(output_path),
                generated_at=now,
                generated_by_account_id=self._session.account_id,
            )
            self._record_audit(
                action_type="template.generate",
                entity_id=template.id,
                created_at=now,
                details=(
                    f"version={version.version_number};"
                    f"version_id={version_id};output={output_path}"
                ),
            )
            self._conn.commit()
            record = self._repo.get_generated(generated_id)
            assert record is not None
            return record
        except Exception:
            self._conn.rollback()
            raise

    def _to_view(self, record: TemplateRecord) -> TemplateView:
        versions = self._repo.list_versions(record.id)
        latest = versions[-1].version_number if versions else None
        return TemplateView(
            id=record.id,
            name=record.name,
            format=record.format,
            is_archived=record.is_archived,
            latest_version=latest,
        )

    def _to_version_view(self, record: TemplateVersionRecord) -> TemplateVersionView:
        return TemplateVersionView(
            id=record.id,
            template_id=record.template_id,
            version_number=record.version_number,
            binding_mode=record.binding_mode,
            contract_version=record.contract_version,
        )

    def _require_version(self, version_id: int) -> TemplateVersionRecord:
        version = self._repo.get_version(version_id)
        if version is None:
            raise TemplateLibraryError("template version not found")
        return version

    def _require_manage(self) -> None:
        self._session.require_unlocked()
        self._authz.require(self._session.role, Permission.MANAGE_REPORT_TEMPLATES)

    def _require_use(self) -> None:
        self._session.require_unlocked()
        if not (
            self._authz.check(self._session.role, Permission.USE_ACTIVE_REPORT_TEMPLATES)
            or self._authz.check(self._session.role, Permission.MANAGE_REPORT_TEMPLATES)
        ):
            raise AuthorizationError(
                f"permission denied: {Permission.USE_ACTIVE_REPORT_TEMPLATES.value}"
            )

    def _record_audit(
        self,
        *,
        action_type: str,
        entity_id: int,
        created_at: str,
        details: str | None = None,
    ) -> None:
        self._audit.record(
            account_id=self._session.account_id,
            action_type=action_type,
            result="success",
            created_at=created_at,
            entity_type=ENTITY_TEMPLATE,
            entity_id=entity_id,
            details=details,
        )


def _detect_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return "excel"
    if suffix == ".pdf":
        return "pdf"
    raise TemplateLibraryError(f"unsupported template format: {suffix or path.name}")


def _stored_name(fmt: str) -> str:
    return "original.xlsx" if fmt == "excel" else "original.pdf"
