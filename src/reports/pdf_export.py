"""Табличный PDF стандартного отчёта (reportlab, не шаблон EPIC-011)."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from domain.reports import ReportTable

_FONT_NAME = "ReportSans"
_FONT_REGISTERED = False


def write_report_pdf(path: Path, table: ReportTable) -> None:
    _ensure_font()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        title=table.title,
        pageCompression=0,
    )
    styles = getSampleStyleSheet()
    styles["Title"].fontName = _FONT_NAME
    styles["Normal"].fontName = _FONT_NAME
    story = [
        Paragraph(table.title, styles["Title"]),
        Spacer(1, 12),
        _table(table),
    ]
    doc.build(story)


def pdf_page_count(path: Path) -> int:
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        return 0
    return max(data.count(b"/Type /Page") - data.count(b"/Type /Pages"), 1)


def pdf_contains_text(path: Path, needle: str) -> bool:
    raw = path.read_bytes()
    if needle.encode("utf-8") in raw or needle.encode("utf-16-be") in raw:
        return True
    import zlib

    marker = b"stream\n"
    end = b"\nendstream"
    start = 0
    while True:
        i = raw.find(marker, start)
        if i < 0:
            return False
        j = raw.find(end, i)
        if j < 0:
            return False
        chunk = raw[i + len(marker) : j]
        try:
            plain = zlib.decompress(chunk)
        except zlib.error:
            plain = chunk
        if needle.encode("utf-8") in plain or needle.encode("latin-1", "ignore") in plain:
            return True
        start = j + len(end)


def _table(table: ReportTable) -> Table:
    grouped = any(row.group_label for row in table.rows)
    header = list(table.columns) if not grouped else ["Группа", *table.columns]
    data = [header]
    for row in table.rows:
        data.append(list(row.cells) if not grouped else [row.group_label, *row.cells])
    if len(data) == 1:
        data.append(["—"] * len(header))
    grid = Table(data, repeatRows=1)
    grid.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B2A3D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E1E1DC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return grid


def _ensure_font() -> None:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    font_path = _find_font()
    if font_path is None:
        raise RuntimeError("no Cyrillic TTF found (install fonts-dejavu-core)")
    pdfmetrics.registerFont(TTFont(_FONT_NAME, str(font_path)))
    _FONT_REGISTERED = True


def _find_font() -> Path | None:
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return path
    return None
