"""Integration: EPIC-018 conversion file ingest and session staging (ADR-0012)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from data.import_sessions import ImportSessionRepository
from domain.import_conversion import file_content_hash
from services.bootstrap import BootstrapService
from services.employee_files import write_xlsx
from services.import_conversion_ingest import ImportConversionIngestService
from tests.fixtures.synthetic import seed_synthetic_org

_T0 = "2026-09-25T10:00:00Z"
_T1 = "2026-09-25T12:00:00Z"


def _open(tmp_path: Path):
    clock = lambda: _T0  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    seed_synthetic_org(conn)
    sessions = ImportSessionRepository(conn)
    ingest = ImportConversionIngestService(
        conn, session, sessions=sessions, clock=clock
    )
    return conn, session, ingest, sessions


def _write_csv(path: Path) -> bytes:
    text = (
        "ФИО,Должность,Филиал,Секрет\n"
        "Иванов Иван,,Москва\n"
        ",Инженер,Москва\n"
        "Петров Пётр,,\n"
    )
    path.write_text(text, encoding="utf-8")
    return path.read_bytes()


def _write_xlsx(path: Path) -> bytes:
    write_xlsx(
        path,
        ["ФИО", "Должность", "Неизвестно"],
        [
            ["Сидоров Сидор", "Инженер", "drop-me"],
            ["", "X", "Y"],
            ["Кузнецова Ольга", "", ""],
        ],
    )
    return path.read_bytes()


@pytest.mark.acceptance
def test_csv_ingest_maps_headers_and_filters_fio(tmp_path: Path) -> None:
    conn, _session, ingest, sessions = _open(tmp_path)
    path = tmp_path / "staff.csv"
    raw = _write_csv(path)

    result = ingest.ingest_file(path)

    assert result.resumed is False
    assert result.file_content_hash == file_content_hash(raw)
    assert result.staged_row_count == 2
    rows = sessions.list_rows(result.session_id)
    assert [r.source_row_number for r in rows] == [2, 4]
    first = json.loads(rows[0].values_json)
    assert set(first.keys()) <= {"full_name", "position", "branch"}
    assert "Секрет" not in first
    assert first["full_name"] == "Иванов Иван"
    second = json.loads(rows[1].values_json)
    assert second["full_name"] == "Петров Пётр"
    assert second.get("position", "") == ""
    conn.close()


@pytest.mark.acceptance
def test_xlsx_ingest_discards_unknown_columns(tmp_path: Path) -> None:
    conn, _session, ingest, sessions = _open(tmp_path)
    path = tmp_path / "staff.xlsx"
    raw = _write_xlsx(path)

    result = ingest.ingest_file(path)
    assert result.file_content_hash == hashlib.sha256(raw).hexdigest()
    rows = sessions.list_rows(result.session_id)
    assert len(rows) == 2
    payload = json.loads(rows[0].values_json)
    assert payload == {"full_name": "Сидоров Сидор", "position": "Инженер"}
    conn.close()


@pytest.mark.acceptance
def test_resume_pending_session_without_reingest(tmp_path: Path, monkeypatch) -> None:
    conn, _session, ingest, sessions = _open(tmp_path)
    path = tmp_path / "staff.csv"
    _write_csv(path)
    first = ingest.ingest_file(path)
    before_rows = sessions.list_rows(first.session_id)
    touched_at = sessions.get_by_file_content_hash(first.file_content_hash)
    assert touched_at is not None
    last_accessed = touched_at.last_accessed_at

    second = ingest.ingest_file(path)

    assert second.resumed is True
    assert second.session_id == first.session_id
    assert second.staged_row_count == len(before_rows)
    after_rows = sessions.list_rows(second.session_id)
    assert len(after_rows) == len(before_rows)
    assert [r.id for r in after_rows] == [r.id for r in before_rows]
    assert (
        sessions.get_by_file_content_hash(first.file_content_hash).last_accessed_at
        == last_accessed
    )

    read_calls = {"count": 0}
    from services.employee_files import read_tabular as original_read

    def counting_read(path):
        read_calls["count"] += 1
        return original_read(path)

    monkeypatch.setattr(
        "services.import_conversion_ingest.read_tabular", counting_read
    )
    third = ingest.ingest_file(path)
    assert third.resumed is True
    assert read_calls["count"] == 0
    conn.close()


@pytest.mark.acceptance
def test_new_session_after_completed_empty_session(tmp_path: Path) -> None:
    conn, _session, ingest, sessions = _open(tmp_path)
    path = tmp_path / "staff.csv"
    _write_csv(path)
    first = ingest.ingest_file(path)
    for row in sessions.list_rows(first.session_id):
        sessions.delete_row(row.id)
    sessions.delete_empty_session(first.session_id)
    conn.commit()
    assert sessions.get_by_file_content_hash(first.file_content_hash) is None

    second = ingest.ingest_file(path)
    assert second.resumed is False
    assert second.staged_row_count == 2
    assert len(sessions.list_rows(second.session_id)) == 2
    conn.close()


@pytest.mark.acceptance
def test_different_raw_bytes_create_different_sessions(tmp_path: Path) -> None:
    conn, _session, ingest, sessions = _open(tmp_path)
    path_a = tmp_path / "a.csv"
    path_b = tmp_path / "b.csv"
    path_a.write_text("ФИО\nАльфа\n", encoding="utf-8")
    path_b.write_text("ФИО\nБета\n", encoding="utf-8")

    result_a = ingest.ingest_file(path_a)
    result_b = ingest.ingest_file(path_b)

    assert result_a.file_content_hash != result_b.file_content_hash
    assert result_a.session_id != result_b.session_id
    conn.close()


@pytest.mark.acceptance
def test_ingest_lazy_cleanup_removes_stale_sessions(tmp_path: Path) -> None:
    _T_NOW = "2026-09-25T10:00:00Z"
    _STALE = "2026-08-20T10:00:00Z"
    clock = lambda: _T_NOW  # noqa: E731
    conn, session, _code = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=tmp_path / "app.db", login="admin", password="AdminPass-1"
    )
    seed_synthetic_org(conn)
    sessions = ImportSessionRepository(conn)
    stale_id = sessions.create_session(file_content_hash="b" * 64, last_accessed_at=_STALE)
    sessions.insert_row(
        session_id=stale_id,
        source_row_number=2,
        values_json='{"full_name": "Старый"}',
    )
    conn.commit()
    ingest = ImportConversionIngestService(
        conn, session, sessions=sessions, clock=clock
    )
    path = tmp_path / "fresh.csv"
    path.write_text("ФИО\nНовый\n", encoding="utf-8")

    result = ingest.ingest_file(path)

    assert sessions.get_by_file_content_hash("b" * 64) is None
    assert result.staged_row_count == 1
    assert len(sessions.list_rows(result.session_id)) == 1
    conn.close()


@pytest.mark.acceptance
def test_ingest_failure_rolls_back_session_and_rows(tmp_path: Path, monkeypatch) -> None:
    conn, _session, ingest, sessions = _open(tmp_path)
    path = tmp_path / "staff.csv"
    _write_csv(path)
    calls = {"count": 0}

    original_insert = sessions.insert_row

    def failing_insert(**kwargs):
        calls["count"] += 1
        if calls["count"] >= 2:
            raise RuntimeError("insert failed")
        return original_insert(**kwargs)

    monkeypatch.setattr(sessions, "insert_row", failing_insert)

    with pytest.raises(RuntimeError, match="insert failed"):
        ingest.ingest_file(path)

    assert sessions.get_by_file_content_hash(file_content_hash(path.read_bytes())) is None
    assert conn.execute("SELECT COUNT(*) FROM import_session_rows").fetchone()[0] == 0
    conn.close()
