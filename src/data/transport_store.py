"""TransportKeyStore persistence facade (EPIC-019)."""

from __future__ import annotations

from data.db import Connection
from data.transport_store_chain import TransportChainStore
from data.transport_store_identities import TransportIdentityStore


class TransportStoreRepository(TransportIdentityStore, TransportChainStore):
    """Combined repository for identity/trust and direction/WK/package state."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
