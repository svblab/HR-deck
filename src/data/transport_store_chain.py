"""Transport direction, WK chain, and package-record persistence (EPIC-019)."""

from __future__ import annotations

from typing import Any

from data.db import Connection
from domain.transport import (
    DirectionState,
    DirectionStatus,
    PackageClassification,
    PackageRecord,
    TransportKeyError,
    WkKeyRecord,
    WkRole,
)


def _row_wk(row: Any) -> WkKeyRecord:
    return WkKeyRecord(
        id=int(row[0]),
        key_id=str(row[1]),
        direction_id=int(row[2]),
        sequence_established=row[3],
        wk_key_material=bytes(row[4]),
        wk_role=WkRole(row[5]),
        predecessor_key_id=row[6],
    )


def _row_direction(row: Any) -> DirectionState:
    return DirectionState(
        id=int(row[0]),
        sender_installation_id=str(row[1]),
        recipient_installation_id=str(row[2]),
        peer_trust_id=int(row[3]),
        accepted_sequence=int(row[4]),
        current_wk_id=row[5],
        direction_status=DirectionStatus(row[6]),
    )


class TransportChainStore:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def ensure_direction(
        self,
        *,
        sender_installation_id: str,
        recipient_installation_id: str,
        peer_trust_id: int,
        now: str,
    ) -> DirectionState:
        row = self._conn.execute(
            "SELECT id, sender_installation_id, recipient_installation_id, peer_trust_id,"
            " accepted_sequence, current_wk_id, direction_status"
            " FROM transport_direction_state"
            " WHERE sender_installation_id = ? AND recipient_installation_id = ?",
            (sender_installation_id, recipient_installation_id),
        ).fetchone()
        if row is not None:
            return _row_direction(row)
        cur = self._conn.execute(
            "INSERT INTO transport_direction_state ("
            " sender_installation_id, recipient_installation_id, peer_trust_id,"
            " accepted_sequence, direction_status, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?, ?)",
            (
                sender_installation_id,
                recipient_installation_id,
                peer_trust_id,
                DirectionStatus.ACTIVE.value,
                now,
                now,
            ),
        )
        direction_id = int(cur.lastrowid)
        return DirectionState(
            id=direction_id,
            sender_installation_id=sender_installation_id,
            recipient_installation_id=recipient_installation_id,
            peer_trust_id=peer_trust_id,
            accepted_sequence=0,
            current_wk_id=None,
            direction_status=DirectionStatus.ACTIVE,
        )

    def get_direction(self, direction_id: int) -> DirectionState | None:
        row = self._conn.execute(
            "SELECT id, sender_installation_id, recipient_installation_id, peer_trust_id,"
            " accepted_sequence, current_wk_id, direction_status"
            " FROM transport_direction_state WHERE id = ?",
            (direction_id,),
        ).fetchone()
        return None if row is None else _row_direction(row)

    def wire_key_id_exists(self, key_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM transport_wk_keys WHERE key_id = ? LIMIT 1", (key_id,)
        ).fetchone()
        return row is not None

    def insert_wk_key(
        self,
        *,
        key_id: str,
        direction_id: int,
        wk_key_material: bytes,
        wk_role: WkRole,
        sequence_established: int | None,
        predecessor_key_id: str | None,
        now: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO transport_wk_keys ("
            " key_id, direction_id, sequence_established, wk_key_material, wk_role,"
            " predecessor_key_id, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key_id,
                direction_id,
                sequence_established,
                wk_key_material,
                wk_role.value,
                predecessor_key_id,
                now,
            ),
        )
        return int(cur.lastrowid)

    def lookup_wk_by_key_id(self, key_id: str) -> WkKeyRecord | None:
        row = self._conn.execute(
            "SELECT id, key_id, direction_id, sequence_established, wk_key_material,"
            " wk_role, predecessor_key_id"
            " FROM transport_wk_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        return None if row is None else _row_wk(row)

    def get_wk_by_id(self, wk_row_id: int) -> WkKeyRecord | None:
        row = self._conn.execute(
            "SELECT id, key_id, direction_id, sequence_established, wk_key_material,"
            " wk_role, predecessor_key_id"
            " FROM transport_wk_keys WHERE id = ?",
            (wk_row_id,),
        ).fetchone()
        return None if row is None else _row_wk(row)

    def retire_active_wk_for_direction(self, direction_id: int, *, now: str) -> None:
        self._conn.execute(
            "UPDATE transport_wk_keys"
            " SET wk_role = ?, retired_at = ?"
            " WHERE direction_id = ? AND wk_role = ?",
            (WkRole.HISTORICAL.value, now, direction_id, WkRole.ACTIVE.value),
        )

    def set_wk_role(self, key_id: str, role: WkRole, *, now: str) -> None:
        self._conn.execute(
            "UPDATE transport_wk_keys SET wk_role = ?, retired_at = ? WHERE key_id = ?",
            (role.value, now, key_id),
        )

    def set_direction_current_wk(
        self,
        direction_id: int,
        *,
        wk_row_id: int,
        accepted_sequence: int,
        now: str,
    ) -> None:
        self._conn.execute(
            "UPDATE transport_direction_state"
            " SET current_wk_id = ?, accepted_sequence = ?, updated_at = ?, direction_status = ?"
            " WHERE id = ?",
            (
                wk_row_id,
                accepted_sequence,
                now,
                DirectionStatus.ACTIVE.value,
                direction_id,
            ),
        )

    def set_direction_status(self, direction_id: int, status: DirectionStatus, *, now: str) -> None:
        self._conn.execute(
            "UPDATE transport_direction_state"
            " SET direction_status = ?, updated_at = ? WHERE id = ?",
            (status.value, now, direction_id),
        )

    def reset_direction_chain(self, direction_id: int, *, now: str) -> None:
        self._conn.execute(
            "UPDATE transport_direction_state"
            " SET accepted_sequence = 0, current_wk_id = NULL,"
            " direction_status = ?, updated_at = ?"
            " WHERE id = ?",
            (DirectionStatus.REINIT_REQUIRED.value, now, direction_id),
        )

    def find_package(self, package_id: str) -> PackageRecord | None:
        row = self._conn.execute(
            "SELECT id, direction_id, package_id, sequence, classification, envelope_key_id"
            " FROM transport_package_records WHERE package_id = ?",
            (package_id,),
        ).fetchone()
        if row is None:
            return None
        return PackageRecord(
            id=int(row[0]),
            direction_id=int(row[1]),
            package_id=str(row[2]),
            sequence=int(row[3]),
            classification=PackageClassification(row[4]),
            envelope_key_id=row[5],
        )

    def max_accepted_sequence(self, direction_id: int) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM transport_package_records"
            " WHERE direction_id = ? AND classification = ?",
            (direction_id, PackageClassification.ACCEPTED.value),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def insert_package_record(
        self,
        *,
        direction_id: int,
        package_id: str,
        sequence: int,
        classification: PackageClassification,
        envelope_key_id: str | None,
        rejection_reason: str | None,
        now: str,
        accepted_at: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO transport_package_records ("
            " direction_id, package_id, sequence, classification, rejection_reason,"
            " envelope_key_id, first_seen_at, last_seen_at, accepted_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                direction_id,
                package_id,
                sequence,
                classification.value,
                rejection_reason,
                envelope_key_id,
                now,
                now,
                accepted_at,
            ),
        )
        return int(cur.lastrowid)

    def touch_package_replay(self, package_id: str, *, now: str) -> None:
        cur = self._conn.execute(
            "UPDATE transport_package_records"
            " SET last_seen_at = ?"
            " WHERE package_id = ? AND classification = ?",
            (
                now,
                package_id,
                PackageClassification.ACCEPTED.value,
            ),
        )
        if cur.rowcount == 0:
            raise TransportKeyError(f"package not accepted for replay: {package_id}")
