"""Экспорт таблицы стандартного отчёта в XLSX (openpyxl)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from domain.reports import ReportTable


def write_report_xlsx(path: Path, table: ReportTable) -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = table.title.replace(":", " —")[:31]
    sheet.append([table.title])
    headers = list(table.columns) if not _has_groups(table) else ["Группа", *table.columns]
    sheet.append(headers)
    for row in table.rows:
        if _has_groups(table):
            sheet.append([row.group_label, *row.cells])
        else:
            sheet.append(list(row.cells))
    book.save(path)


def _has_groups(table: ReportTable) -> bool:
    return any(row.group_label for row in table.rows)
