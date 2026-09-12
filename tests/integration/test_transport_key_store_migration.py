"""Migration 0009: TransportKeyStore schema on nonempty DB + FK enforcement."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from data.db import connect, create_database, generate_master_key, table_columns
from data.migrations import apply_pending_migrations, current_version, default_migrations_dir
from tests.fixtures.synthetic import seed_synthetic_org

TRANSPORT_TABLES = {
    "transport_installation",
    "transport_local_signing_keys",
    "transport_local_bootstrap_keys",
    "transport_peer_trust",
    "transport_direction_state",
    "transport_wk_keys",
    "transport_package_records",
}


def _migrations_through(version: int, root: Path) -> Path:
    target = root / "migrations"
    target.mkdir()
    for path in sorted(default_migrations_dir().glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, target / path.name)
    return target


@pytest.mark.acceptance
def test_migration_0009_on_nonempty_db(tmp_path: Path) -> None:
    key = generate_master_key()
    path = tmp_path / "app.db"
    mig_v8 = _migrations_through(8, tmp_path)
    conn = create_database(path, key)
    assert apply_pending_migrations(conn, migrations_dir=mig_v8) == list(range(1, 9))
    ids = seed_synthetic_org(conn)
    emp_name = conn.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0]
    conn.close()

    conn2 = connect(path, key)
    applied = apply_pending_migrations(conn2)
    assert applied == [9]
    assert current_version(conn2) == 9
    tables = {
        r[0]
        for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert TRANSPORT_TABLES <= tables
    assert "current_wk_id" in table_columns(conn2, "transport_direction_state")
    assert conn2.execute(
        "SELECT full_name FROM employees WHERE id=?", (ids["employee_a_id"],)
    ).fetchone()[0] == emp_name
    conn2.close()


@pytest.mark.acceptance
def test_current_wk_id_fk_rejects_missing_reference(tmp_path: Path) -> None:
    key = generate_master_key()
    conn = create_database(tmp_path / "app.db", key)
    apply_pending_migrations(conn)
    now = "2026-09-12T00:00:00Z"
    conn.execute(
        "INSERT INTO transport_installation"
        " (installation_id, display_label, created_at, updated_at)"
        " VALUES ('local', 'Local', ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO transport_peer_trust ("
        " peer_installation_id, signing_public_key, signing_key_fingerprint,"
        " bootstrap_public_key, bootstrap_key_fingerprint, trusted_at"
        ") VALUES ('peer', X'01', 'fp-sign', X'02', 'fp-boot', ?)",
        (now,),
    )
    peer_id = conn.execute("SELECT id FROM transport_peer_trust").fetchone()[0]
    conn.execute(
        "INSERT INTO transport_direction_state ("
        " sender_installation_id, recipient_installation_id, peer_trust_id,"
        " accepted_sequence, direction_status, created_at, updated_at"
        ") VALUES ('local', 'peer', ?, 0, 'active', ?, ?)",
        (peer_id, now, now),
    )
    conn.commit()
    with pytest.raises(sqlcipher.IntegrityError):
        conn.execute(
            "UPDATE transport_direction_state SET current_wk_id = 99999 WHERE id = 1"
        )
