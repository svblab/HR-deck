"""Unit tests for ImportSessionRepository (EPIC-018 / ADR-0012)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import create_database, generate_master_key
from data.import_sessions import ImportSessionRepository
from data.migrations import apply_pending_migrations

_T0 = "2026-09-01T10:00:00Z"
_T1 = "2026-09-20T10:00:00Z"
_T2 = "2026-09-25T10:00:00Z"
_HASH_A = "a" * 64
_HASH_B = "b" * 64
_JSON_ONE = '{"full_name":"Иванов"}'
_JSON_TWO = '{"full_name":"Петров","branch":"Москва"}'


@pytest.fixture()
def repo(tmp_path: Path) -> ImportSessionRepository:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    return ImportSessionRepository(conn)


def test_create_and_lookup_by_hash(repo: ImportSessionRepository) -> None:
    session_id = repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T1)
    found = repo.get_by_file_content_hash(_HASH_A)
    assert found is not None
    assert found.id == session_id
    assert found.file_content_hash == _HASH_A
    assert found.last_accessed_at == _T1
    assert repo.get_by_file_content_hash("missing") is None


def test_insert_rows_ordered_and_preserve_values_json(repo: ImportSessionRepository) -> None:
    session_id = repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T1)
    repo.insert_row(session_id=session_id, source_row_number=5, values_json=_JSON_TWO)
    repo.insert_row(session_id=session_id, source_row_number=2, values_json=_JSON_ONE)

    rows = repo.list_rows(session_id)
    assert [r.source_row_number for r in rows] == [2, 5]
    assert rows[0].values_json == _JSON_ONE
    assert rows[1].values_json == _JSON_TWO
    assert rows[0].session_id == session_id
    assert rows[1].session_id == session_id


def test_duplicate_source_row_number_rejected(repo: ImportSessionRepository) -> None:
    session_id = repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T1)
    repo.insert_row(session_id=session_id, source_row_number=2, values_json=_JSON_ONE)
    with pytest.raises(sqlcipher.IntegrityError):
        repo.insert_row(session_id=session_id, source_row_number=2, values_json='{"x":1}')


def test_duplicate_file_content_hash_rejected(repo: ImportSessionRepository) -> None:
    repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T1)
    with pytest.raises(sqlcipher.IntegrityError):
        repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T2)


def test_delete_one_row_leaves_others(repo: ImportSessionRepository) -> None:
    session_id = repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T1)
    first_id = repo.insert_row(
        session_id=session_id, source_row_number=2, values_json=_JSON_ONE
    )
    second_id = repo.insert_row(
        session_id=session_id, source_row_number=5, values_json=_JSON_TWO
    )
    repo.delete_row(first_id)

    remaining = repo.list_rows(session_id)
    assert len(remaining) == 1
    assert remaining[0].id == second_id
    assert remaining[0].source_row_number == 5


def test_touch_updates_last_accessed_at(repo: ImportSessionRepository) -> None:
    session_id = repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T1)
    repo.touch_session(session_id, last_accessed_at=_T2)
    found = repo.get_by_file_content_hash(_HASH_A)
    assert found is not None
    assert found.last_accessed_at == _T2


def test_delete_empty_session_only_when_no_rows(repo: ImportSessionRepository) -> None:
    session_id = repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T1)
    row_id = repo.insert_row(
        session_id=session_id, source_row_number=2, values_json=_JSON_ONE
    )

    assert repo.delete_empty_session(session_id) is False
    assert repo.get_by_file_content_hash(_HASH_A) is not None
    assert repo.list_rows(session_id)[0].id == row_id

    repo.delete_row(row_id)
    assert repo.delete_empty_session(session_id) is True
    assert repo.get_by_file_content_hash(_HASH_A) is None


def test_purge_all_removes_sessions_and_rows(repo: ImportSessionRepository) -> None:
    session_a = repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T1)
    session_b = repo.create_session(file_content_hash=_HASH_B, last_accessed_at=_T1)
    repo.insert_row(session_id=session_a, source_row_number=2, values_json=_JSON_ONE)
    repo.insert_row(session_id=session_b, source_row_number=3, values_json=_JSON_TWO)

    repo.purge_all()

    assert repo.get_by_file_content_hash(_HASH_A) is None
    assert repo.get_by_file_content_hash(_HASH_B) is None
    assert repo.list_rows(session_a) == []
    assert repo.list_rows(session_b) == []


def test_delete_stale_before_cutoff(repo: ImportSessionRepository) -> None:
    old_id = repo.create_session(file_content_hash=_HASH_A, last_accessed_at=_T0)
    recent_id = repo.create_session(file_content_hash=_HASH_B, last_accessed_at=_T2)
    repo.insert_row(session_id=old_id, source_row_number=2, values_json=_JSON_ONE)
    recent_row = repo.insert_row(
        session_id=recent_id, source_row_number=3, values_json=_JSON_TWO
    )

    removed = repo.delete_stale_before(_T1)
    assert removed == 1

    assert repo.get_by_file_content_hash(_HASH_A) is None
    assert repo.list_rows(old_id) == []
    assert repo.get_by_file_content_hash(_HASH_B) is not None
    assert len(repo.list_rows(recent_id)) == 1
    assert repo.list_rows(recent_id)[0].id == recent_row

    repo.delete_row(recent_row)
    assert repo.list_rows(recent_id) == []
