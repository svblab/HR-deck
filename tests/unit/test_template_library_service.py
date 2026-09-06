"""Unit: TemplateLibraryService wraps reports.* validation errors at the service boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from reports.excel_template import TemplateValidationError
from reports.pdf_template import PdfTemplateValidationError
from services.bootstrap import BootstrapService
from services.template_library import TemplateLibraryError, TemplateLibraryService


def _save_excel(path: Path, marker: str) -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet["A1"] = marker
    book.save(path)
    book.close()


def _plain_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawString(72, 720, "no form")
    c.save()


def _library(tmp_path: Path) -> tuple[object, TemplateLibraryService]:
    clock = lambda: "2026-08-30T12:00:00Z"  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    library = TemplateLibraryService(conn, session, data_dir=tmp_path, clock=clock)
    return conn, library


def test_upload_unknown_excel_marker_raises_template_library_error(
    tmp_path: Path,
) -> None:
    conn, library = _library(tmp_path)
    src = tmp_path / "bad.xlsx"
    _save_excel(src, "{{неизвестный_маркер}}")
    with pytest.raises(TemplateLibraryError, match="неизвестный_маркер") as exc:
        library.upload_version(name="Плохой", source=src)
    assert not isinstance(exc.value, TemplateValidationError)
    conn.close()


def test_upload_malformed_excel_marker_raises_template_library_error(
    tmp_path: Path,
) -> None:
    conn, library = _library(tmp_path)
    src = tmp_path / "malformed.xlsx"
    _save_excel(src, "{{должность}")
    with pytest.raises(TemplateLibraryError) as exc:
        library.upload_version(name="Опечатка", source=src)
    assert "TemplateValidationError" not in type(exc.value).__name__
    assert str(exc.value)
    conn.close()


def test_upload_invalid_pdf_raises_template_library_error(tmp_path: Path) -> None:
    conn, library = _library(tmp_path)
    src = tmp_path / "plain.pdf"
    _plain_pdf(src)
    with pytest.raises(TemplateLibraryError, match="no acroform") as exc:
        library.upload_version(name="PDF без формы", source=src)
    assert not isinstance(exc.value, PdfTemplateValidationError)
    conn.close()
