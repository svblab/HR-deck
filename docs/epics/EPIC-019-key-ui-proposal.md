# EPIC-019 — Key/trust management UI proposal (diff-first)

**Status:** Awaiting human approval (ANCHOR_PROTOCOL.md §5)  
**Branch:** `epic/EPIC-019-backup-and-key-ui`  
**Base:** EPIC-019 service layer merged (PR #65)  
**Scope:** Proposal only — no dialog implementation, no menu wiring.

Per ROADMAP EPIC-019: *«UI не работает с сырыми ключами напрямую»* — all UI
actions must call **`TransportKeyAdminService`** only, never `TransportKeyStore`
directly.

Precedents: `src/ui/directories_dialog.py` (tabbed admin CRUD, permission-gated
panels), `src/ui/backup_dialog.py` (admin-only service facade, modal dialog,
`has_permission` at construct time).

---

## 1. Screen inventory (admin actions)

| # | Admin need | UI surface (proposed) |
|---|---|---|
| 1 | View local **signing** identity: fingerprint, status (`active` / `lost` / …), created_at | **Tab «Локальная установка»** — read-only labels; button «Создать идентичности» if none (calls bootstrap) |
| 2 | View local **bootstrap encryption** identity: fingerprint, status | Same tab, separate section (never merged with signing) |
| 3 | Mark local signing or bootstrap identity **lost** | Same tab — «Пометить signing как утерян» / «Пометить bootstrap как утерян» (confirm dialog) |
| 4 | **Register peer trust** after out-of-band exchange | **Tab «Доверенные установки»** — form: peer `installation_id`, display label, signing public key (hex/base64 paste), signing fingerprint, bootstrap public key, bootstrap fingerprint → «Добавить peer» |
| 5 | View registered peers: fingerprints, signing/bootstrap trust status | **Tab «Доверенные установки»** — table of peers |
| 6 | Revoke peer **signing** or **bootstrap** trust (`revoked` / `compromised`) | Peer table row actions |
| 7 | View **per-direction** state: sender→recipient, `direction_status`, `accepted_sequence`, current wire `key_id` | **Tab «Направления»** — table keyed by `(sender, recipient)` |
| 8 | Revoke / mark-lost an active **WK** (`compromised` / `lost`) | Direction detail or WK sub-table — select `key_id`, choose revoke reason |
| 9 | **Manual re-init** for broken direction (`reinit_required`) | Direction row — «Переинициализировать направление» (confirm: resets sequence + `current_wk_id`) |

Out of scope for v1 UI (EPIC-020): package export/import, wire codec, business payload.

---

## 2. Service method mapping

### Already on `TransportKeyAdminService` (UI-ready — commits + audit)

| UI action | Method |
|---|---|
| Bootstrap local signing + bootstrap identities | `bootstrap_local_identities()` → `(signing_fp, bootstrap_fp)` |
| Register peer trust | `register_peer(...)` |

### On `TransportKeyStore` only — **missing from `TransportKeyAdminService`**

These exist on the store layer but have **no admin facade** yet. UI v1 requires
thin wrappers (authz + audit + commit) before the dialog can call them:

| UI action | `TransportKeyStore` method | Proposed admin wrapper |
|---|---|---|
| View local installation / fingerprints | `ensure_local_installation()`, repo reads | **`list_local_identity()`** — read-only query returning fingerprints + statuses (new read method on admin service, no store commit) |
| Mark local signing lost | `mark_local_signing_lost()` | **`mark_local_signing_lost()`** |
| Mark local bootstrap lost | `mark_local_bootstrap_lost()` | **`mark_local_bootstrap_lost()`** |
| List peers | via `TransportStoreRepository.get_peer_trust` / SQL | **`list_peer_trust()`** |
| Revoke peer signing | `revoke_peer_signing(peer_trust_id, status=...)` | **`revoke_peer_signing(...)`** |
| Revoke peer bootstrap | `revoke_peer_bootstrap(peer_trust_id, status=...)` | **`revoke_peer_bootstrap(...)`** |
| List directions + current WK | `get_direction`, `lookup_wk_by_key_id` | **`list_direction_states()`** |
| Revoke WK | `revoke_wk(key_id, role=...)` | **`revoke_wk(...)`** |
| Re-init direction | `reinit_direction(direction_id)` | **`reinit_direction(direction_id)`** |

**Follow-up before UI implementation:** one small service PR adding the nine
admin wrappers above (read methods + mutate methods with audit action types
`transport.identity.lost`, `transport.peer.revoke`, `transport.wk.revoke`,
`transport.direction.reinit`, …). Estimated ~120 lines in
`transport_key_admin.py`, no schema change.

---

## 3. Permission gating

- **Permission:** `Permission.MANAGE_ENCRYPTION_KEYS` (administrator only per
  ADR-0007; already in `domain/permissions.py`, included in `_ALL` for
  `RoleCode.ADMINISTRATOR`).
- **Entry point pattern** (match `backup_dialog.py` / `main_window.py`):
  - Toolbar or settings-area button visible/enabled only when
    `has_permission(session.role, Permission.MANAGE_ENCRYPTION_KEYS)`.
  - Dialog constructor stores `self._can_manage = has_permission(...)` and
    disables mutating controls when false (read-only mode not required — HR and
    Observer never see the button).
- **Service layer:** every `TransportKeyAdminService` mutator already calls
  `_require_admin()` → `authz.require(..., MANAGE_ENCRYPTION_KEYS)`.

---

## 4. File layout and size estimate

| File | Role | Est. lines |
|---|---|---|
| `src/ui/transport_keys_dialog.py` | Main `QDialog` + `QTabWidget` shell | ~120 |
| `src/ui/transport_keys_panels.py` | Tab panels (local / peers / directions) | ~280 |
| `tests/unit/test_transport_keys_ui.py` | Permission gating + smoke (qtbot) | ~120 |

**Total ~520 lines** — exceeds 300-line diff-first threshold as a single file.

**Recommended split (matches EPIC-021 direction):**

1. **Tab per concern** inside one dialog (same pattern as `DirectoriesDialog`):
   - Tab 1: Local identity
   - Tab 2: Peer trust
   - Tab 3: Direction / WK state
2. **Two source files:** dialog shell + panels module (above).
3. **Defer EPIC-021 unified «Работа с базой данных»** merge until EPIC-019 tab
   is stable — wire a standalone «Ключи и доверие…» button on main window
   (admin-only) in the implementation PR, same as current backup ⚙ entry.

Do **not** implement until this proposal is approved and admin service wrappers
from §2 are merged.

---

## Approval checkpoint

**Do not implement** dialog, menu wiring, or new admin service methods until
the human reviewer approves this inventory and the follow-up service-layer scope.

---

## Traceability

| Artifact | Link |
|---|---|
| EPIC-019 ROADMAP | `docs/ROADMAP.md` § EPIC-019 |
| ADR-0007 | `docs/adr/ADR-0007-branch-sync-encryption.md` |
| Service layer | `src/services/transport_key_admin.py`, `src/services/transport_keys.py` |
| UI precedents | `src/ui/directories_dialog.py`, `src/ui/backup_dialog.py` |
