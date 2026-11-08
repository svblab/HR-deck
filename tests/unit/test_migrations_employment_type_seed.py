"""Unit: E1-01 employment type seed migration contract shape (ADR-0011 §1.1)."""

from __future__ import annotations

import re

from data.migrations import default_migrations_dir

_MIGRATION_NAME = "0020_employment_type_seed_transferred_erroneous.sql"
_ABORT_MESSAGE = "employment type seed contract mismatch"


def _migration_sql() -> str:
    path = default_migrations_dir() / _MIGRATION_NAME
    assert path.is_file(), f"missing migration {path}"
    return path.read_text(encoding="utf-8")


def test_contract_mismatch_uses_raise_abort_inside_before_insert_trigger() -> None:
    sql = _migration_sql()
    assert "BEFORE INSERT ON _employment_type_seed" in sql
    abort = f"RAISE(ABORT, '{_ABORT_MESSAGE}')"
    assert abort in sql

    trigger_block = re.search(
        r"CREATE\s+TEMP\s+TRIGGER\s+trg_employment_type_seed_contract\s+"
        r"BEFORE\s+INSERT\s+ON\s+_employment_type_seed\s+"
        r"BEGIN(?P<body>.*?)END\s*;",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert trigger_block is not None, "TEMP BEFORE INSERT trigger not found"
    body = trigger_block.group("body")
    assert abort in body
    assert "employment type seed contract mismatch" in body
    assert re.search(
        r"SELECT\s+RAISE\s*\(\s*ABORT\s*,\s*'employment type seed contract mismatch'\s*\)\s+"
        r"WHERE\s+EXISTS",
        body,
        re.IGNORECASE | re.DOTALL,
    )

    # No bare SELECT RAISE(...) outside the trigger (ADR-0011 §1.1).
    outside = sql[: trigger_block.start()] + sql[trigger_block.end() :]
    assert "employment type seed contract mismatch" not in outside
    assert re.search(r"RAISE\s*\(\s*ABORT", outside, re.IGNORECASE) is None
    bare_outside = re.compile(
        r"SELECT\s+RAISE\s*\(\s*ABORT\s*,\s*'employment type seed contract mismatch'\s*\)\s*;",
        re.IGNORECASE,
    )
    assert bare_outside.search(outside) is None


def test_seed_uses_insert_select_where_not_exists_without_fixed_id() -> None:
    sql = _migration_sql()
    for code in ("transferred", "erroneous"):
        pattern = (
            rf"INSERT\s+INTO\s+employment_types\s*\([^)]*\)\s*"
            rf"SELECT\s+'{code}'\s*,.*?WHERE\s+NOT\s+EXISTS\s*\("
            rf"\s*SELECT\s+1\s+FROM\s+employment_types\s+WHERE\s+code\s*=\s*'{code}'\s*\)"
        )
        assert re.search(pattern, sql, re.IGNORECASE | re.DOTALL), code
        assert not re.search(
            r"INSERT\s+INTO\s+employment_types\s*\([^)]*\bid\b[^)]*\)",
            sql,
            re.IGNORECASE,
        )
