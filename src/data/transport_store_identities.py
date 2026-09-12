"""Transport identity and peer-trust persistence (EPIC-019)."""

from __future__ import annotations

import uuid

from data.db import Connection
from domain.transport import LocalInstallation, LocalKeyStatus, PeerTrustRecord, TrustStatus


class TransportIdentityStore:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_local_installation(self) -> LocalInstallation | None:
        row = self._conn.execute(
            "SELECT installation_id, display_label FROM transport_installation LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return LocalInstallation(str(row[0]), row[1])

    def create_local_installation(self, *, display_label: str | None, now: str) -> str:
        installation_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO transport_installation (installation_id, display_label, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (installation_id, display_label, now, now),
        )
        return installation_id

    def insert_local_signing_key(
        self,
        *,
        public_key: bytes,
        private_key: bytes,
        fingerprint: str,
        status: LocalKeyStatus,
        now: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO transport_local_signing_keys ("
            " public_key, private_key, key_fingerprint, key_status, created_at"
            ") VALUES (?, ?, ?, ?, ?)",
            (public_key, private_key, fingerprint, status.value, now),
        )
        return int(cur.lastrowid)

    def insert_local_bootstrap_key(
        self,
        *,
        public_key: bytes,
        private_key: bytes,
        fingerprint: str,
        status: LocalKeyStatus,
        now: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO transport_local_bootstrap_keys ("
            " public_key, private_key, key_fingerprint, key_status, created_at"
            ") VALUES (?, ?, ?, ?, ?)",
            (public_key, private_key, fingerprint, status.value, now),
        )
        return int(cur.lastrowid)

    def get_active_signing_fingerprint(self) -> str | None:
        row = self._conn.execute(
            "SELECT key_fingerprint FROM transport_local_signing_keys"
            " WHERE key_status = ? LIMIT 1",
            (LocalKeyStatus.ACTIVE.value,),
        ).fetchone()
        return None if row is None else str(row[0])

    def supersede_active_signing(self, *, status: LocalKeyStatus, now: str) -> None:
        self._conn.execute(
            "UPDATE transport_local_signing_keys"
            " SET key_status = ?, superseded_at = ?"
            " WHERE key_status = ?",
            (status.value, now, LocalKeyStatus.ACTIVE.value),
        )

    def supersede_active_bootstrap(self, *, status: LocalKeyStatus, now: str) -> None:
        self._conn.execute(
            "UPDATE transport_local_bootstrap_keys"
            " SET key_status = ?, superseded_at = ?"
            " WHERE key_status = ?",
            (status.value, now, LocalKeyStatus.ACTIVE.value),
        )

    def insert_peer_trust(
        self,
        *,
        peer_installation_id: str,
        display_label: str | None,
        signing_public_key: bytes,
        signing_fingerprint: str,
        bootstrap_public_key: bytes,
        bootstrap_fingerprint: str,
        now: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO transport_peer_trust ("
            " peer_installation_id, display_label,"
            " signing_public_key, signing_key_fingerprint, signing_trust_status,"
            " bootstrap_public_key, bootstrap_key_fingerprint, bootstrap_trust_status,"
            " trusted_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                peer_installation_id,
                display_label,
                signing_public_key,
                signing_fingerprint,
                TrustStatus.ACTIVE.value,
                bootstrap_public_key,
                bootstrap_fingerprint,
                TrustStatus.ACTIVE.value,
                now,
            ),
        )
        return int(cur.lastrowid)

    def get_peer_trust(self, peer_trust_id: int) -> PeerTrustRecord | None:
        row = self._conn.execute(
            "SELECT id, peer_installation_id, display_label,"
            " signing_public_key, signing_key_fingerprint, signing_trust_status,"
            " bootstrap_public_key, bootstrap_key_fingerprint, bootstrap_trust_status"
            " FROM transport_peer_trust WHERE id = ?",
            (peer_trust_id,),
        ).fetchone()
        if row is None:
            return None
        return PeerTrustRecord(
            id=int(row[0]),
            peer_installation_id=str(row[1]),
            display_label=row[2],
            signing_public_key=bytes(row[3]),
            signing_key_fingerprint=str(row[4]),
            signing_trust_status=TrustStatus(row[5]),
            bootstrap_public_key=bytes(row[6]),
            bootstrap_key_fingerprint=str(row[7]),
            bootstrap_trust_status=TrustStatus(row[8]),
        )

    def set_peer_signing_trust_status(
        self, peer_trust_id: int, status: TrustStatus, *, now: str
    ) -> None:
        self._conn.execute(
            "UPDATE transport_peer_trust"
            " SET signing_trust_status = ?, revoked_at = ?"
            " WHERE id = ?",
            (status.value, now, peer_trust_id),
        )

    def set_peer_bootstrap_trust_status(
        self, peer_trust_id: int, status: TrustStatus, *, now: str
    ) -> None:
        self._conn.execute(
            "UPDATE transport_peer_trust"
            " SET bootstrap_trust_status = ?, revoked_at = ?"
            " WHERE id = ?",
            (status.value, now, peer_trust_id),
        )
