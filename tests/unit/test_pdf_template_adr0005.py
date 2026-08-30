"""Unit: PDF template engine (ADR-0005 §PDF)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from reports.pdf_export import pdf_contains_text
from reports.pdf_template import (
    PdfTemplateValidationError,
    archive_pdf_upload,
    generate_pdf_report,
    regions_manifest_path,
    validate_pdf,
)


def _plain_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawString(72, 720, "Plain template")
    c.save()


def _acroform_pdf(path: Path, *field_names: str) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    form = c.acroForm
    y = 700
    for name in field_names:
        form.textfield(name=name, x=72, y=y, width=240, height=18, forceBorder=True)
        y -= 30
    c.save()


def test_adr0005_pdf_no_form_no_manifest_rejected_on_upload(tmp_path: Path) -> None:
    src = tmp_path / "plain.pdf"
    _plain_pdf(src)
    with pytest.raises(PdfTemplateValidationError, match="no acroform"):
        validate_pdf(src)


def test_adr0005_pdf_unknown_field_rejected_on_upload(tmp_path: Path) -> None:
    src = tmp_path / "bad.pdf"
    _acroform_pdf(src, "not_in_catalog")
    with pytest.raises(PdfTemplateValidationError) as exc:
        validate_pdf(src)
    assert "not_in_catalog" in exc.value.unknown_fields


def test_adr0005_pdf_acroform_fields_filled(tmp_path: Path) -> None:
    src = tmp_path / "form.pdf"
    _acroform_pdf(src, "employee.full_name", "ФИО")
    archive = tmp_path / "store" / "orig.pdf"
    archived = archive_pdf_upload(src, archive)
    out = tmp_path / "out.pdf"
    generate_pdf_report(
        archived,
        out,
        {"employee.full_name": "Иванов Иван"},
    )
    assert pdf_contains_text(out, "Иванов")


def test_adr0005_pdf_regions_manifest_fields_filled(tmp_path: Path) -> None:
    src = tmp_path / "flat.pdf"
    _plain_pdf(src)
    manifest = regions_manifest_path(src)
    manifest.write_text(
        json.dumps(
            {
                "contract_version": "1.0",
                "binding_mode": "regions",
                "regions": [
                    {
                        "field": "employee.full_name",
                        "page": 1,
                        "x_pt": 72.0,
                        "y_pt": 700.0,
                        "width_pt": 200.0,
                        "height_pt": 14.0,
                        "font_size_pt": 10.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "store" / "orig.pdf"
    archived = archive_pdf_upload(src, archive, manifest_source=manifest)
    out = tmp_path / "out.pdf"
    generate_pdf_report(archived, out, {"employee.full_name": "Петров"})
    assert pdf_contains_text(out, "Петров")


def test_adr0005_pdf_archive_unchanged_after_generation(tmp_path: Path) -> None:
    src = tmp_path / "form.pdf"
    _acroform_pdf(src, "report.title")
    archive = tmp_path / "orig.pdf"
    archived = archive_pdf_upload(src, archive)
    before = hashlib.sha256(archive.read_bytes()).hexdigest()
    generate_pdf_report(archived, tmp_path / "filled.pdf", {"report.title": "Отчёт"})
    after = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert before == after


def test_adr0005_pdf_missing_value_renders_empty(tmp_path: Path) -> None:
    src = tmp_path / "form.pdf"
    _acroform_pdf(src, "employee.full_name")
    archived = archive_pdf_upload(src, tmp_path / "orig.pdf")
    out = tmp_path / "out.pdf"
    generate_pdf_report(archived, out, {})
    assert out.is_file()
