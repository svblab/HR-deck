"""TransportKeyStore service — authoritative transport state in personnel.db (EPIC-019)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from data.transport_crypto import (
    generate_bootstrap_keypair,
    generate_signing_keypair,
    generate_wire_key_id,
    generate_wk_material,
)
from data.transport_store import TransportStoreRepository
from domain.transport import (
    DirectionState,
    DirectionStatus,
    LocalInstallation,
    LocalKeyStatus,
    PackageClassification,
    TransportKeyError,
    TrustStatus,
    WkKeyRecord,
    WkRole,
)

Clock = Callable[[], str]
MAX_KEY_ID_ATTEMPTS = 8


@dataclass(frozen=True)
class AcceptPackageResult:
    package_record_id: int
    wk_row_id: int | None
    replay: bool


class TransportKeyStore:
    """
    Mutable transport state inside the caller's SQLite transaction.

    This class never calls commit() or rollback(); orchestrators and admin
    facades own the transaction boundary (ADR-0007).
    """

    def __init__(
        self,
        conn,
        *,
        clock: Clock | None = None,
        repo: TransportStoreRepository | None = None,
    ) -> None:
        from datetime import UTC, datetime

        self._conn = conn
        self._clock = clock or (
            lambda: datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        self._repo = repo or TransportStoreRepository(conn)

    def ensure_local_installation(self, *, display_label: str | None = None) -> LocalInstallation:
        existing = self._repo.get_local_installation()
        if existing is not None:
            return existing
        now = self._clock()
        installation_id = self._repo.create_local_installation(display_label=display_label, now=now)
        return LocalInstallation(installation_id, display_label)

    def generate_local_signing_identity(self) -> str:
        if self._repo.get_active_signing_fingerprint() is not None:
            raise TransportKeyError("active signing identity already exists")
        pair = generate_signing_keypair()
        self._repo.insert_local_signing_key(
            public_key=pair.public_key,
            private_key=pair.private_key,
            fingerprint=pair.fingerprint,
            status=LocalKeyStatus.ACTIVE,
            now=self._clock(),
        )
        return pair.fingerprint

    def generate_local_bootstrap_identity(self) -> str:
        row = self._conn.execute(
            "SELECT 1 FROM transport_local_bootstrap_keys WHERE key_status = ? LIMIT 1",
            (LocalKeyStatus.ACTIVE.value,),
        ).fetchone()
        if row is not None:
            raise TransportKeyError("active bootstrap identity already exists")
        pair = generate_bootstrap_keypair()
        self._repo.insert_local_bootstrap_key(
            public_key=pair.public_key,
            private_key=pair.private_key,
            fingerprint=pair.fingerprint,
            status=LocalKeyStatus.ACTIVE,
            now=self._clock(),
        )
        return pair.fingerprint

    def mark_local_signing_lost(self) -> None:
        now = self._clock()
        self._repo.supersede_active_signing(status=LocalKeyStatus.LOST, now=now)

    def mark_local_bootstrap_lost(self) -> None:
        now = self._clock()
        self._repo.supersede_active_bootstrap(status=LocalKeyStatus.LOST, now=now)

    def register_peer_trust(
        self,
        *,
        peer_installation_id: str,
        display_label: str | None,
        signing_public_key: bytes,
        signing_fingerprint: str,
        bootstrap_public_key: bytes,
        bootstrap_fingerprint: str,
    ) -> int:
        return self._repo.insert_peer_trust(
            peer_installation_id=peer_installation_id,
            display_label=display_label,
            signing_public_key=signing_public_key,
            signing_fingerprint=signing_fingerprint,
            bootstrap_public_key=bootstrap_public_key,
            bootstrap_fingerprint=bootstrap_fingerprint,
            now=self._clock(),
        )

    def revoke_peer_signing(self, peer_trust_id: int, *, status: TrustStatus) -> None:
        if status == TrustStatus.ACTIVE:
            raise TransportKeyError("cannot revoke to active")
        self._repo.set_peer_signing_trust_status(peer_trust_id, status, now=self._clock())

    def revoke_peer_bootstrap(self, peer_trust_id: int, *, status: TrustStatus) -> None:
        if status == TrustStatus.ACTIVE:
            raise TransportKeyError("cannot revoke to active")
        self._repo.set_peer_bootstrap_trust_status(peer_trust_id, status, now=self._clock())

    def ensure_direction(
        self,
        *,
        sender_installation_id: str,
        recipient_installation_id: str,
        peer_trust_id: int,
    ) -> DirectionState:
        return self._repo.ensure_direction(
            sender_installation_id=sender_installation_id,
            recipient_installation_id=recipient_installation_id,
            peer_trust_id=peer_trust_id,
            now=self._clock(),
        )

    def allocate_wire_key_id(self) -> str:
        for _ in range(MAX_KEY_ID_ATTEMPTS):
            key_id = generate_wire_key_id()
            if not self._repo.wire_key_id_exists(key_id):
                return key_id
        raise TransportKeyError("failed to allocate unique wire key_id")

    def create_wk_key(
        self,
        *,
        direction_id: int,
        wk_role: WkRole,
        sequence_established: int | None = None,
        predecessor_key_id: str | None = None,
        wk_material: bytes | None = None,
        wire_key_id: str | None = None,
    ) -> WkKeyRecord:
        key_id = wire_key_id or self.allocate_wire_key_id()
        if self._repo.wire_key_id_exists(key_id):
            raise TransportKeyError(f"wire key_id collision: {key_id}")
        material = wk_material or generate_wk_material()
        now = self._clock()
        row_id = self._repo.insert_wk_key(
            key_id=key_id,
            direction_id=direction_id,
            wk_key_material=material,
            wk_role=wk_role,
            sequence_established=sequence_established,
            predecessor_key_id=predecessor_key_id,
            now=now,
        )
        record = self._repo.get_wk_by_id(row_id)
        if record is None:
            raise TransportKeyError("wk insert failed")
        return record

    def lookup_wk_by_key_id(self, key_id: str) -> WkKeyRecord | None:
        return self._repo.lookup_wk_by_key_id(key_id)

    def activate_wk_for_direction(
        self,
        *,
        direction_id: int,
        wk_row_id: int,
        accepted_sequence: int,
    ) -> None:
        wk = self._repo.get_wk_by_id(wk_row_id)
        if wk is None:
            raise TransportKeyError(f"unknown wk row id: {wk_row_id}")
        if wk.direction_id != direction_id:
            raise TransportKeyError("wk direction mismatch")
        now = self._clock()
        self._repo.retire_active_wk_for_direction(direction_id, now=now)
        self._conn.execute(
            "UPDATE transport_wk_keys SET wk_role = ?, sequence_established = ? WHERE id = ?",
            (WkRole.ACTIVE.value, accepted_sequence, wk_row_id),
        )
        self._repo.set_direction_current_wk(
            direction_id,
            wk_row_id=wk_row_id,
            accepted_sequence=accepted_sequence,
            now=now,
        )

    def revoke_wk(self, key_id: str, *, role: WkRole) -> None:
        if role in {WkRole.ACTIVE, WkRole.HISTORICAL}:
            raise TransportKeyError("invalid revoke target role")
        wk = self._repo.lookup_wk_by_key_id(key_id)
        if wk is None:
            raise TransportKeyError(f"unknown key_id: {key_id}")
        self._repo.set_wk_role(key_id, role, now=self._clock())
        direction = self._repo.get_direction(wk.direction_id)
        if direction is not None and direction.current_wk_id == wk.id:
            self._repo.set_direction_status(
                wk.direction_id, DirectionStatus.BROKEN, now=self._clock()
            )

    def reinit_direction(self, direction_id: int) -> None:
        self._repo.reset_direction_chain(direction_id, now=self._clock())

    def record_package_acceptance(
        self,
        *,
        direction_id: int,
        package_id: str,
        sequence: int,
        envelope_key_id: str | None,
        next_wk: WkKeyRecord | None = None,
        accepted_sequence: int | None = None,
    ) -> AcceptPackageResult:
        existing = self._repo.find_package(package_id)
        if existing is not None:
            if existing.classification == PackageClassification.ACCEPTED:
                self._repo.touch_package_replay(package_id, now=self._clock())
                return AcceptPackageResult(existing.id, None, replay=True)
            raise TransportKeyError(f"package_id already used: {package_id}")

        max_seq = self._repo.max_accepted_sequence(direction_id)
        if sequence <= max_seq:
            raise TransportKeyError("stale or consumed sequence")

        now = self._clock()
        wk_row_id: int | None = None
        if next_wk is not None:
            wk_row_id = next_wk.id
            self.activate_wk_for_direction(
                direction_id=direction_id,
                wk_row_id=wk_row_id,
                accepted_sequence=accepted_sequence or sequence,
            )

        record_id = self._repo.insert_package_record(
            direction_id=direction_id,
            package_id=package_id,
            sequence=sequence,
            classification=PackageClassification.ACCEPTED,
            envelope_key_id=envelope_key_id,
            rejection_reason=None,
            now=now,
            accepted_at=now,
        )
        return AcceptPackageResult(record_id, wk_row_id, replay=False)

    def record_package_rejection(
        self,
        *,
        direction_id: int,
        package_id: str,
        sequence: int,
        envelope_key_id: str | None,
        reason: str,
    ) -> int:
        return self._repo.insert_package_record(
            direction_id=direction_id,
            package_id=package_id,
            sequence=sequence,
            classification=PackageClassification.REJECTED,
            envelope_key_id=envelope_key_id,
            rejection_reason=reason,
            now=self._clock(),
        )
