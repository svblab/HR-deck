"""PDF-шаблоны: валидация при загрузке и генерация (ADR-0005 §PDF)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from domain.template_markers import (
    CANONICAL_KEYS,
    CONTRACT_VERSION,
    canonical_key,
    find_malformed_marker_fragments,
)
from reports.pdf_export import _find_font

BindingMode = Literal["acroform", "regions"]


class PdfTemplateError(Exception):
    """Ошибка PDF-шаблона."""


class PdfTemplateValidationError(PdfTemplateError):
    def __init__(
        self,
        message: str,
        *,
        unknown_fields: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.unknown_fields = unknown_fields


@dataclass(frozen=True)
class RegionSpec:
    field: str
    page: int
    x_pt: float
    y_pt: float
    width_pt: float
    height_pt: float
    font_size_pt: float = 10.0


@dataclass(frozen=True)
class ArchivedPdfTemplate:
    archive_path: Path
    binding: BindingMode
    manifest_path: Path | None = None
    contract_version: str = CONTRACT_VERSION
    regions: tuple[RegionSpec, ...] = ()


def regions_manifest_path(pdf_path: Path) -> Path:
    return pdf_path.with_suffix(".regions.json")


def archive_pdf_upload(
    source: Path,
    archive_path: Path,
    *,
    manifest_source: Path | None = None,
) -> ArchivedPdfTemplate:
    """Validate, then store PDF (and optional manifest) byte-for-byte."""
    manifest = manifest_source or regions_manifest_path(source)
    manifest_arg = manifest if manifest.is_file() else None
    archived = validate_pdf(source, manifest_path=manifest_arg)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(source.read_bytes())
    stored_manifest: Path | None = None
    if archived.binding == "regions" and manifest_arg is not None:
        stored_manifest = archive_path.with_suffix(".regions.json")
        stored_manifest.write_bytes(manifest_arg.read_bytes())
    return ArchivedPdfTemplate(
        archive_path=archive_path,
        binding=archived.binding,
        manifest_path=stored_manifest,
        regions=archived.regions,
    )


def validate_pdf(source: Path, *, manifest_path: Path | None = None) -> ArchivedPdfTemplate:
    try:
        reader = _reader(source)
    except PdfReadError as exc:
        raise PdfTemplateValidationError("invalid pdf") from exc
    if reader.is_encrypted:
        raise PdfTemplateValidationError("password-protected pdf")

    field_names = _acroform_field_names(reader)
    if field_names:
        for index, name in enumerate(field_names):
            malformed = find_malformed_marker_fragments(name)
            if malformed:
                raise PdfTemplateValidationError(
                    "malformed marker syntax in acroform field "
                    f"index {index}: {malformed[0]!r}"
                )
        unknown = tuple(sorted(name for name in field_names if canonical_key(name) is None))
        if unknown:
            raise PdfTemplateValidationError(
                f"unknown acroform fields: {', '.join(unknown)}",
                unknown_fields=unknown,
            )
        return ArchivedPdfTemplate(archive_path=source, binding="acroform")

    manifest = manifest_path or regions_manifest_path(source)
    if not manifest.is_file():
        raise PdfTemplateValidationError("pdf has no acroform fields and no regions manifest")
    regions = _load_regions_manifest(manifest)
    return ArchivedPdfTemplate(
        archive_path=source,
        binding="regions",
        manifest_path=manifest,
        regions=regions,
    )


def generate_pdf_report(
    archived: ArchivedPdfTemplate,
    output_path: Path,
    values: dict[str, str],
) -> None:
    """Produce a derived PDF; archived originals are not modified."""
    shutil.copyfile(archived.archive_path, output_path)
    if archived.binding == "acroform":
        _fill_acroform(archived.archive_path, output_path, values)
    else:
        _fill_regions(archived.archive_path, output_path, archived.regions, values)


def _reader(path: Path) -> PdfReader:
    return PdfReader(str(path))


def _acroform_field_names(reader: PdfReader) -> list[str]:
    fields = reader.get_fields()
    if not fields:
        return []
    return list(fields.keys())


def _load_regions_manifest(path: Path) -> tuple[RegionSpec, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PdfTemplateValidationError("invalid regions manifest") from exc
    if payload.get("contract_version") != CONTRACT_VERSION:
        raise PdfTemplateValidationError("unsupported regions contract_version")
    if payload.get("binding_mode") != "regions":
        raise PdfTemplateValidationError("binding_mode must be regions")
    raw = payload.get("regions")
    if not isinstance(raw, list) or not raw:
        raise PdfTemplateValidationError("regions manifest has no regions")
    specs: list[RegionSpec] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PdfTemplateValidationError("invalid region entry")
        field = str(item.get("field", ""))
        malformed = find_malformed_marker_fragments(field)
        if malformed:
            raise PdfTemplateValidationError(
                "malformed marker syntax in regions manifest "
                f"region index {index}: {malformed[0]!r}"
            )
        if field not in CANONICAL_KEYS:
            raise PdfTemplateValidationError(f"unknown region field: {field}")
        specs.append(
            RegionSpec(
                field=field,
                page=int(item["page"]),
                x_pt=float(item["x_pt"]),
                y_pt=float(item["y_pt"]),
                width_pt=float(item["width_pt"]),
                height_pt=float(item["height_pt"]),
                font_size_pt=float(item.get("font_size_pt", 10.0)),
            )
        )
    return tuple(specs)


def _fill_acroform(source: Path, output_path: Path, values: dict[str, str]) -> None:
    reader = _reader(source)
    writer = PdfWriter()
    writer.append(reader)
    fill = {
        name: values.get(canonical_key(name) or "", "")
        for name in _acroform_field_names(reader)
        if canonical_key(name) is not None
    }
    for page in writer.pages:
        writer.update_page_form_field_values(page, fill, auto_regenerate=False)
    with output_path.open("wb") as handle:
        writer.write(handle)


def _fill_regions(
    source: Path,
    output_path: Path,
    regions: tuple[RegionSpec, ...],
    values: dict[str, str],
) -> None:
    reader = _reader(source)
    writer = PdfWriter()
    writer.append(reader)
    font_name = _overlay_font()
    by_page: dict[int, list[RegionSpec]] = {}
    for region in regions:
        by_page.setdefault(region.page, []).append(region)

    for page_index, page_regions in by_page.items():
        if page_index < 1 or page_index > len(writer.pages):
            raise PdfTemplateError(f"region page out of range: {page_index}")
        page = writer.pages[page_index - 1]
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        packet = BytesIO()
        overlay = canvas.Canvas(packet, pagesize=(width, height))
        overlay.setFont(font_name, page_regions[0].font_size_pt)
        for region in page_regions:
            overlay.setFont(font_name, region.font_size_pt)
            overlay.drawString(region.x_pt, region.y_pt, values.get(region.field, ""))
        overlay.save()
        packet.seek(0)
        overlay_reader = PdfReader(packet)
        page.merge_page(overlay_reader.pages[0])

    with output_path.open("wb") as handle:
        writer.write(handle)


def _overlay_font() -> str:
    path = _find_font()
    name = "TemplateOverlay"
    if path is not None and name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(path)))
        return name
    return "Helvetica"
