# EPIC-019 Phase 0 — TransportKeyStore proposal (diff-first)

**Status:** Awaiting human approval (ANCHOR_PROTOCOL.md §5)  
**Branch:** `epic/EPIC-019-transport-key-store`  
**Base:** ADR-0007 v3 (Принято, PR #64)  
**Scope:** Proposal only — no service logic, UI, or tests in this PR.

This document satisfies the diff-first checkpoint before implementing migration
0009, `TransportKeyStore` service code, and interop tests.

---

## 1. Crypto library selection

### Decision

Use the **existing** [`cryptography`](https://pypi.org/project/cryptography/) package
already declared in `pyproject.toml` (`cryptography>=50,<51`) and used for
SQLCipher keywrap (`src/data/keywrap.py`). **No new dependency is added.**

At implementation time, tighten the pin to a single patch release:

```text
cryptography==50.0.1
```

**Resolved (reviewer 2026-09-12):** exact pin `==50.0.1` applied in
`pyproject.toml` (reviewer accepts manual bump risk for future security patches).

### Primitive mapping (ADR-0007 → `cryptography` API)

| ADR-0007 primitive | Algorithm | `cryptography` API (50.x) |
|---|---|---|
| Signing identity | Ed25519 (EdDSA) | `cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey` / `Ed25519PublicKey` |
| Bootstrap encryption identity | X25519 (ECDH) | `cryptography.hazmat.primitives.asymmetric.x25519.X25519PrivateKey` / `X25519PublicKey` |
| Per-package `SK_n` and envelope `WK` | AES-256-GCM (AEAD) | `cryptography.hazmat.primitives.ciphers.aead.AESGCM` (same class as keywrap) |

**Bootstrap first-envelope wrap:** X25519 ECDH → shared secret → HKDF-SHA256
(`cryptography.hazmat.primitives.kdf.hkdf.HKDF`) → AES-256-GCM key for wrapping
`WK_1` material. Exact KDF info string and AAD labels are part of canonical
serialization (§3) and will be fixed in the implementation PR.

**Rejected alternatives**

| Option | Why not |
|---|---|
| PyNaCl / `libsodium` | New dependency; duplicates primitives already available in `cryptography`; ADR-0007 v2 Box model explicitly rejected. |
| `pycryptodome` | New dependency; stack already standardized on `cryptography` for AEAD keywrap. |
| Split libraries (e.g. `cryptography` + `nacl`) | Unnecessary operational surface; one audited stack is sufficient. |

### ADR gate

- **ADR-0007** already accepts algorithm families and defers library choice to
  implementation.
- **`cryptography` is already in the project dependency list** — this proposal
  selects concrete APIs within that package, not a net-new stack entry.
- **No separate ADR file required** unless the reviewer wants an ADR-0001 addendum
  explicitly naming transport crypto APIs (optional documentation only).

---

## 2. TransportKeyStore SQL schema (`personnel.db`)

### Design principles (ADR-0007 invariants)

1. **Single database** — all tables below live in encrypted `personnel.db`
   (SQLCipher + `personnel.db.keywrap`). No sidecar `keys.enc`.
2. **At-rest protection** — whole-DB encryption; `wk_key_material` and local
   private keys are BLOB columns protected by SQLCipher (no additional plaintext
   file). Application layer treats them as sensitive secrets in memory only.
3. **Signing ≠ bootstrap encryption** — separate local key tables and separate
   peer trust columns; never a combined “identity” row.
4. **`key_id` uniqueness** — globally unique within the installation
   (`UNIQUE` on `transport_wk_keys.key_id`).
5. **Historical WK never auto-promoted** — `wk_role` CHECK constraint; only
   service logic on successful package accept may set `active`; historical rows
   are verify/decrypt-only.
6. **Duplex independence** — direction state keyed by
   `(sender_installation_id, recipient_installation_id)`; no shared sequence
   across directions.
7. **Replay/idempotency** — `transport_package_records.package_id` UNIQUE for
   exact-replay lookup; partial unique index on accepted `(direction_id, sequence)`.

### Table list

| Table | Purpose |
|---|---|
| `transport_installation` | Local installation identity (`installation_id` UUID used in protocol routing). |
| `transport_local_signing_keys` | Own signing keypairs (active + historical/superseded for audit). |
| `transport_local_bootstrap_keys` | Own bootstrap encryption keypairs (active + historical). |
| `transport_peer_trust` | Per-peer trusted signing + bootstrap **public** keys and revocation state. |
| `transport_direction_state` | Per-direction chain head: `accepted_sequence`, pointer to current `WK`. |
| `transport_wk_keys` | All `WK` material with globally unique `key_id` and lifecycle role. |
| `transport_package_records` | Package acceptance / replay / rejection audit trail (authoritative for freshness). |

### Entity relationships (conceptual)

```text
transport_installation (1 row, local)
    ├── transport_local_signing_keys (1 active, N historical)
    └── transport_local_bootstrap_keys (1 active, N historical)

transport_peer_trust (N peers)
    └── transport_direction_state (2 × N directions: outbound + inbound per peer pair)
            ├── transport_wk_keys (chain, keyed by direction_id + key_id)
            └── transport_package_records (acceptance/replay log)
```

### Migration skeleton

Number **0009** follows existing convention (`0001`…`0008` in
`src/data/migrations/`). Full DDL for review:

```sql
-- EPIC-019 Phase 0: TransportKeyStore schema skeleton (ADR-0007 v3).
-- PROPOSAL ONLY — apply logic/triggers/service code in a follow-up PR after approval.

PRAGMA foreign_keys = ON;

-- Local installation identity (protocol routing peer id for this copy).
CREATE TABLE transport_installation (
    installation_id TEXT PRIMARY KEY,
    display_label TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Own signing identity keypairs (Ed25519). Separate from bootstrap encryption.
CREATE TABLE transport_local_signing_keys (
    id INTEGER PRIMARY KEY,
    public_key BLOB NOT NULL,
    private_key BLOB NOT NULL,
    key_fingerprint TEXT NOT NULL UNIQUE,
    key_status TEXT NOT NULL DEFAULT 'active'
        CHECK (key_status IN ('active', 'superseded', 'lost', 'compromised')),
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    notes TEXT
);

CREATE UNIQUE INDEX idx_transport_local_signing_active
    ON transport_local_signing_keys (key_status)
    WHERE key_status = 'active';

-- Own bootstrap encryption identity keypairs (X25519). Separate from signing.
CREATE TABLE transport_local_bootstrap_keys (
    id INTEGER PRIMARY KEY,
    public_key BLOB NOT NULL,
    private_key BLOB NOT NULL,
    key_fingerprint TEXT NOT NULL UNIQUE,
    key_status TEXT NOT NULL DEFAULT 'active'
        CHECK (key_status IN ('active', 'superseded', 'lost', 'compromised')),
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    notes TEXT
);

CREATE UNIQUE INDEX idx_transport_local_bootstrap_active
    ON transport_local_bootstrap_keys (key_status)
    WHERE key_status = 'active';

-- Trusted peer public material from manual out-of-band bootstrap.
CREATE TABLE transport_peer_trust (
    id INTEGER PRIMARY KEY,
    peer_installation_id TEXT NOT NULL UNIQUE,
    display_label TEXT,
    signing_public_key BLOB NOT NULL,
    signing_key_fingerprint TEXT NOT NULL,
    signing_trust_status TEXT NOT NULL DEFAULT 'active'
        CHECK (signing_trust_status IN ('active', 'revoked', 'compromised')),
    bootstrap_public_key BLOB NOT NULL,
    bootstrap_key_fingerprint TEXT NOT NULL,
    bootstrap_trust_status TEXT NOT NULL DEFAULT 'active'
        CHECK (bootstrap_trust_status IN ('active', 'revoked', 'compromised')),
    trusted_at TEXT NOT NULL,
    revoked_at TEXT,
    notes TEXT
);

CREATE INDEX idx_transport_peer_trust_signing_fp
    ON transport_peer_trust (signing_key_fingerprint);

-- Per-direction transport chain state (duplex: independent rows per sender→recipient).
CREATE TABLE transport_direction_state (
    id INTEGER PRIMARY KEY,
    sender_installation_id TEXT NOT NULL,
    recipient_installation_id TEXT NOT NULL,
    peer_trust_id INTEGER NOT NULL REFERENCES transport_peer_trust(id),
    accepted_sequence INTEGER NOT NULL DEFAULT 0,
    current_wk_id INTEGER,
    direction_status TEXT NOT NULL DEFAULT 'active'
        CHECK (direction_status IN ('active', 'broken', 'reinit_required')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (sender_installation_id, recipient_installation_id)
);

CREATE INDEX idx_transport_direction_peer
    ON transport_direction_state (peer_trust_id);

-- WK chain material. key_id is globally unique within this installation (ADR-0007).
CREATE TABLE transport_wk_keys (
    id INTEGER PRIMARY KEY,
    key_id TEXT NOT NULL UNIQUE,
    direction_id INTEGER NOT NULL REFERENCES transport_direction_state(id),
    sequence_established INTEGER,
    wk_key_material BLOB NOT NULL,
    wk_role TEXT NOT NULL
        CHECK (wk_role IN ('active', 'historical', 'revoked', 'compromised', 'lost')),
    predecessor_key_id TEXT,
    created_at TEXT NOT NULL,
    retired_at TEXT
);

CREATE INDEX idx_transport_wk_keys_direction
    ON transport_wk_keys (direction_id, sequence_established);

CREATE INDEX idx_transport_wk_keys_role
    ON transport_wk_keys (direction_id, wk_role);

-- Package acceptance / replay / rejection records (freshness + idempotency).
CREATE TABLE transport_package_records (
    id INTEGER PRIMARY KEY,
    direction_id INTEGER NOT NULL REFERENCES transport_direction_state(id),
    package_id TEXT NOT NULL UNIQUE,
    sequence INTEGER NOT NULL,
    classification TEXT NOT NULL
        CHECK (classification IN (
            'accepted',
            'rejected',
            'replay_observed',
            'pending'
        )),
    rejection_reason TEXT,
    envelope_key_id TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    accepted_at TEXT
);

CREATE INDEX idx_transport_package_direction_seq
    ON transport_package_records (direction_id, sequence);

CREATE UNIQUE INDEX idx_transport_package_accepted_sequence
    ON transport_package_records (direction_id, sequence)
    WHERE classification = 'accepted';
```

**Resolved (reviewer 2026-09-12):** `current_wk_id INTEGER` is a **surrogate FK** to
`transport_wk_keys(id)` (renamed from `current_wk_key_id` to avoid confusion with
TEXT wire `key_id`). FK enforced via `ALTER TABLE … ADD COLUMN … REFERENCES
transport_wk_keys(id) ON DELETE RESTRICT` after `transport_wk_keys` exists.
WK rows are never `DELETE`d — lifecycle via `wk_role` only; `ON DELETE RESTRICT`
relies on that invariant. **Insert order:** `INSERT transport_wk_keys` first,
then `UPDATE transport_direction_state.current_wk_id` within the same DB
transaction (ADR-0007 transaction-authoritative invariant).

**Deferred to implementation PR (not in skeleton):**

- Triggers enforcing “at most one `active` WK per direction”.
- Service-layer enforcement of historical WK non-promotion.
- `Permission.MANAGE_ENCRYPTION_KEYS` checks (domain layer, not schema).

---

## 3. Canonical serialization for signed / authenticated fields

### Decision: length-prefixed binary concatenation (`HRTR-CBOR`-free deterministic encoding)

Use a **fixed field-order, big-endian length-prefixed byte concatenation**
(“`TransportCanonicalV1`”). No JSON (key ordering / number formatting /
Unicode normalization ambiguities across Python versions). No new serialization
library.

**Encoding helper (implementation sketch, not shipped in this PR):**

```python
def canon_field_bytes(payload: bytes) -> bytes:
    if len(payload) > 0xFFFFFFFF:
        raise ValueError("field too large")
    return len(payload).to_bytes(4, "big") + payload

def canon_field_utf8(text: str) -> bytes:
    return canon_field_bytes(text.encode("utf-8"))

def canon_field_u32(value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError("u32 out of range")
    return value.to_bytes(4, "big")
```

**Magic and version prefix:** ASCII `HRTR` + `0x01` (protocol canonical version 1).

### A. Signature input (`signing_bytes`)

Ed25519 signs **one** byte string built as:

```text
MAGIC (5) = b"HRTR\x01"
|| canon_field_u32(protocol_version)
|| canon_field_utf8(sender_installation_id)
|| canon_field_utf8(recipient_installation_id)
|| canon_field_u32(sequence)
|| canon_field_utf8(package_id)
|| canon_field_utf8(envelope_key_id)          # key_id for envelope decrypt lookup
|| canon_field_utf8(sender_signing_fingerprint)
|| canon_field_bytes(envelope_ciphertext)     # ciphertext || GCM tag as stored on wire
|| canon_field_bytes(payload_ciphertext)      # ciphertext || GCM tag as stored on wire
|| canon_field_bytes(routing_metadata_bytes)  # canonical cleartext routing blob (see B)
```

Covers ADR-0007 authenticated areas: protocol routing, package identity,
envelope chain references, payload ciphertext, trust context (signing fingerprint).

**Rule:** Any tamper of cleartext routing metadata that is duplicated inside
`routing_metadata_bytes` breaks signature verification when compared after decrypt.

### B. Cleartext routing metadata canonical form (`routing_metadata_bytes`)

Used both on the wire and inside the signature input:

```text
MAGIC (5) = b"HRTM\x01"
|| canon_field_u32(protocol_version)
|| canon_field_utf8(sender_installation_id)
|| canon_field_utf8(recipient_installation_id)
|| canon_field_utf8(envelope_key_id)
|| canon_field_u32(sequence)
|| canon_field_utf8(package_id)
```

Untrusted on read until signature + AEAD succeed; must match authenticated copy.

### C. Envelope AEAD associated data (`envelope_aad`)

AES-GCM / ChaCha20-Poly1305 AAD for envelope encryption under `WK_{n-1}` (or
bootstrap wrap for sequence 1):

```text
MAGIC (5) = b"HRENV\x01"
|| canon_field_u32(protocol_version)
|| canon_field_utf8(sender_installation_id)
|| canon_field_utf8(recipient_installation_id)
|| canon_field_u32(sequence)
|| canon_field_utf8(package_id)
|| canon_field_utf8(envelope_key_id)
|| canon_field_utf8(next_wk_key_id)           # id(WK_{n+1}) established in this package
```

Envelope plaintext (confidential, not in AAD): `SK_n || WK_{n+1}_material || …`.

### D. Payload AEAD associated data (`payload_aad`)

AES-GCM AAD for business payload under `SK_n`:

```text
MAGIC (5) = b"HRPAY\x01"
|| canon_field_u32(protocol_version)
|| canon_field_utf8(sender_installation_id)
|| canon_field_utf8(recipient_installation_id)
|| canon_field_u32(sequence)
|| canon_field_utf8(package_id)
```

### E. Bootstrap first-envelope HKDF info

For X25519-derived wrap key on `sequence = 1`:

```text
HKDF info = b"HRTR-bootstrap-wrap-v1"
    || sender_installation_id_utf8
    || recipient_installation_id_utf8
    || package_id_utf8
```

(salt = ephemeral X25519 shared secret encoding — fixed in implementation tests.)

### Field coverage matrix

| ADR-0007 authenticated concern | Covered in |
|---|---|
| `protocol_version`, direction peer ids | A, B, C, D |
| `package_id`, `sequence` | A, B, C, D |
| `key_id` (envelope) | A, B, C |
| Next `key_id` / `WK_{n+1}` | C (plaintext + AAD) |
| Payload ciphertext integrity | A (signature over ciphertext), D (AEAD) |
| Signing identity | A (`sender_signing_fingerprint`) |
| Sender/recipient substitution | All blocks bind both installation ids |

### Determinism guarantees

- Only `bytes`, `str` → UTF-8, and `u32` integers — **no floats**.
- Explicit lengths — no NUL termination or delimiter ambiguity.
- Big-endian fixed-width integers — stable across CPU/endianness and Python 3.11+.
- Separate magic tags per context prevent cross-protocol replay across AAD domains.

### Test plan (implementation PR, not this proposal)

- Golden-vector tests: same inputs → identical `signing_bytes` on Linux CI.
- Round-trip tamper tests: flip one byte in each covered field → verify failure.
- Cross-block consistency: mismatch cleartext routing vs `routing_metadata_bytes` → reject.

---

## Approval checkpoint

**Status:** Approved 2026-09-12 — implementation proceeds on PR #65.

### Resolved open questions

1. **`current_wk_id` FK** — Renamed from `current_wk_key_id`; surrogate
   `INTEGER REFERENCES transport_wk_keys(id) ON DELETE RESTRICT`. Insert order:
   WK row first, then update `current_wk_id` in the same transaction.
2. **`cryptography` pin** — Exact `==50.0.1` in `pyproject.toml`.

---

## Traceability

| Artifact | Link |
|---|---|
| ADR-0007 v3 | `docs/adr/ADR-0007-branch-sync-encryption.md` |
| EPIC-019 | `docs/ROADMAP.md` § EPIC-019 |
| Migration skeleton | `src/data/migrations/0009_transport_key_store.sql` |
| Diff-first rule | `docs/ANCHOR_PROTOCOL.md` §5 |
