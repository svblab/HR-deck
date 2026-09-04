"""EPIC-016: приёмка сценариев аварийного завершения (TESTING §2.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.db import connect, create_database, generate_master_key
from data.migrations import apply_pending_migrations
from tests.fixtures.synthetic import seed_synthetic_org


@pytest.mark.acceptance
def test_aborted_transaction_leaves_prior_commits_intact(tmp_path: Path) -> None:
    """Симуляция обрыва посреди транзакции: незавершённая запись не сохраняется."""
    key = generate_master_key()
    db_path = tmp_path / "app.db"
    conn = create_database(db_path, key)
    apply_pending_migrations(conn)
    seed_synthetic_org(conn)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 2

    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO employees ("
        " id, full_name, position_id, branch_id, department_id, division_id,"
        " employment_type_id, note, hire_date, is_archived, created_at, updated_at"
        ") VALUES (3, ?, 1, 1, 1, 1, 1, ?, ?, 0, ?, ?)",
        (
            "Обрыв Транзакции Тест",
            "abort-test",
            "2025-01-01",
            "2026-08-01T10:00:00Z",
            "2026-08-01T10:00:00Z",
        ),
    )
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 3
    conn.close()

    conn2 = connect(db_path, key)
    assert conn2.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 2
    names = [r[0] for r in conn2.execute("SELECT full_name FROM employees ORDER BY id")]
    assert names == ["Иванов Иван Иванович", "Иванов Иван Иванович"]
    conn2.close()


@pytest.mark.acceptance
def test_explicit_rollback_discards_uncommitted_mutations(tmp_path: Path) -> None:
    key = generate_master_key()
    db_path = tmp_path / "app.db"
    conn = create_database(db_path, key)
    apply_pending_migrations(conn)
    seed_synthetic_org(conn)
    conn.commit()

    conn.execute("BEGIN")
    conn.execute(
        "UPDATE employees SET note = ? WHERE id = 1",
        ("should-not-persist",),
    )
    conn.rollback()
    note = conn.execute("SELECT note FROM employees WHERE id = 1").fetchone()[0]
    assert note == "синтетика"
    conn.close()
