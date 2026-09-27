"""Out-of-band trust bootstrap helpers (test-harness only — no product API).

Reads local public identity material via SQL, matching existing transport unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from data.db import Connection
from services.transport_key_admin import TransportKeyAdminService
from services.transport_keys import TransportKeyStore


@dataclass(frozen=True)
class LocalIdentityPublics:
    installation_id: str
    signing_public_key: bytes
    signing_fingerprint: str
    bootstrap_public_key: bytes
    bootstrap_fingerprint: str


def read_local_identity_publics(conn: Connection) -> LocalIdentityPublics:
    """Load installation id + active public keys from the encrypted DB (SQL)."""
    inst = conn.execute(
        "SELECT installation_id FROM transport_installation LIMIT 1"
    ).fetchone()
    if inst is None:
        raise RuntimeError("transport installation missing")
    signing = conn.execute(
        "SELECT public_key, key_fingerprint FROM transport_local_signing_keys"
        " WHERE key_status='active' LIMIT 1"
    ).fetchone()
    bootstrap = conn.execute(
        "SELECT public_key, key_fingerprint FROM transport_local_bootstrap_keys"
        " WHERE key_status='active' LIMIT 1"
    ).fetchone()
    if signing is None or bootstrap is None:
        raise RuntimeError("local transport identities missing")
    return LocalIdentityPublics(
        installation_id=str(inst[0]),
        signing_public_key=bytes(signing[0]),
        signing_fingerprint=str(signing[1]),
        bootstrap_public_key=bytes(bootstrap[0]),
        bootstrap_fingerprint=str(bootstrap[1]),
    )


@dataclass(frozen=True)
class DuplexDirections:
    """Outbound = local→peer; inbound = peer→local (receive side)."""

    outbound_id: int
    inbound_id: int


def establish_mutual_trust(
    *,
    admin_a: TransportKeyAdminService,
    store_a: TransportKeyStore,
    conn_a: Connection,
    admin_b: TransportKeyAdminService,
    store_b: TransportKeyStore,
    conn_b: Connection,
    label_a: str,
    label_b: str,
) -> tuple[DuplexDirections, DuplexDirections]:
    """
    Bootstrap identities on both peers, exchange publics via SQL reads, register
    peer trust, and ensure duplex directions. Returns (dirs_a, dirs_b).
    """
    admin_a.bootstrap_local_identities()
    admin_b.bootstrap_local_identities()
    pub_a = read_local_identity_publics(conn_a)
    pub_b = read_local_identity_publics(conn_b)

    peer_on_a = admin_a.register_peer(
        peer_installation_id=pub_b.installation_id,
        display_label=label_b,
        signing_public_key=pub_b.signing_public_key,
        signing_fingerprint=pub_b.signing_fingerprint,
        bootstrap_public_key=pub_b.bootstrap_public_key,
        bootstrap_fingerprint=pub_b.bootstrap_fingerprint,
    )
    peer_on_b = admin_b.register_peer(
        peer_installation_id=pub_a.installation_id,
        display_label=label_a,
        signing_public_key=pub_a.signing_public_key,
        signing_fingerprint=pub_a.signing_fingerprint,
        bootstrap_public_key=pub_a.bootstrap_public_key,
        bootstrap_fingerprint=pub_a.bootstrap_fingerprint,
    )

    out_a = store_a.ensure_direction(
        sender_installation_id=pub_a.installation_id,
        recipient_installation_id=pub_b.installation_id,
        peer_trust_id=peer_on_a,
    )
    in_a = store_a.ensure_direction(
        sender_installation_id=pub_b.installation_id,
        recipient_installation_id=pub_a.installation_id,
        peer_trust_id=peer_on_a,
    )
    out_b = store_b.ensure_direction(
        sender_installation_id=pub_b.installation_id,
        recipient_installation_id=pub_a.installation_id,
        peer_trust_id=peer_on_b,
    )
    in_b = store_b.ensure_direction(
        sender_installation_id=pub_a.installation_id,
        recipient_installation_id=pub_b.installation_id,
        peer_trust_id=peer_on_b,
    )
    conn_a.commit()
    conn_b.commit()
    return (
        DuplexDirections(outbound_id=out_a.id, inbound_id=in_a.id),
        DuplexDirections(outbound_id=out_b.id, inbound_id=in_b.id),
    )
