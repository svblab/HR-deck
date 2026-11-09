"""Unit: запреты шести системных кодов видов занятости (E1-02)."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from data.directories import EmploymentTypeRepository
from domain.employment_types import SYSTEM_EMPLOYMENT_TYPE_CODES
from services.bootstrap import BootstrapService
from services.directories import DirectoryError, DirectoryService

SYSTEM_CODES = (
    "staff",
    "temporary",
    "contractor",
    "dismissed",
    "transferred",
    "erroneous",
)

_CREATE_VARIANTS = [
    (code, raw)
    for code in SYSTEM_CODES
    for raw in (code, code.upper(), f"  {code}  ", f"  {code.upper()}  ")
]


def _open_service(tmp_path: Path) -> DirectoryService:
    db = tmp_path / "app.db"
    bootstrap = BootstrapService(clock=lambda: "2026-08-26T12:00:00Z")
    conn, session, _code = bootstrap.initial_administrator_setup(
        db_path=db,
        login="admin",
        password="AdminPass-1",
    )
    return DirectoryService(conn, session, clock=lambda: "2026-08-26T14:00:00Z")


def _id_by_code(svc: DirectoryService, code: str) -> int:
    return next(row.id for row in svc.list_employment_types() if row.code == code)


def _row_by_id(svc: DirectoryService, employment_type_id: int):
    return next(row for row in svc.list_employment_types() if row.id == employment_type_id)


@pytest.mark.parametrize("code", SYSTEM_CODES)
def test_rename_system_codes_rejected(tmp_path: Path, code: str) -> None:
    svc = _open_service(tmp_path)
    employment_type_id = _id_by_code(svc, code)
    with pytest.raises(
        DirectoryError, match=f"system employment type '{code}' cannot be renamed"
    ):
        svc.rename_employment_type(employment_type_id, "Новое имя")


@pytest.mark.parametrize("code", SYSTEM_CODES)
def test_hide_system_codes_rejected(tmp_path: Path, code: str) -> None:
    svc = _open_service(tmp_path)
    employment_type_id = _id_by_code(svc, code)
    with pytest.raises(
        DirectoryError, match=f"system employment type '{code}' cannot be archived"
    ):
        svc.archive_employment_type(employment_type_id)
    svc.unarchive_employment_type(employment_type_id)
    row = _row_by_id(svc, employment_type_id)
    assert row.is_archived is False


@pytest.mark.parametrize("code,raw", _CREATE_VARIANTS)
def test_create_reserved_code_rejected(tmp_path: Path, code: str, raw: str) -> None:
    svc = _open_service(tmp_path)
    with pytest.raises(
        DirectoryError, match=f"system employment type '{code}' cannot be created"
    ):
        svc.create_employment_type(raw, "Дополнительный")


def test_archives_record_not_changed_for_additional(tmp_path: Path) -> None:
    svc = _open_service(tmp_path)
    new_id = svc.create_employment_type("intern", "Стажёр")
    row = _row_by_id(svc, new_id)
    assert int(row.archives_record) == 0
    svc.rename_employment_type(new_id, "Стажёр-2")
    svc.archive_employment_type(new_id)
    svc.unarchive_employment_type(new_id)
    row = _row_by_id(svc, new_id)
    assert int(row.archives_record) == 0
    assert row.name == "Стажёр-2"
    assert row.is_archived is False
    write_methods = (
        EmploymentTypeRepository.create,
        EmploymentTypeRepository.rename,
        EmploymentTypeRepository.set_archived,
        DirectoryService.create_employment_type,
        DirectoryService.rename_employment_type,
        DirectoryService.archive_employment_type,
        DirectoryService.unarchive_employment_type,
        DirectoryService._set_employment_type_archived,
    )
    for method in write_methods:
        source = inspect.getsource(method)
        assert "archives_record" not in source
    assert SYSTEM_EMPLOYMENT_TYPE_CODES >= set(SYSTEM_CODES)
