# Architecture Audit

Living audit of domain-model gaps, identity contracts, and cross-cutting inconsistencies
between specification, schema, and implementation. Each section is self-contained and cites
evidence in the repository at the time of writing.

**Status:** WORKING (audit in progress)  
**Last updated:** 2026-09-20

**Proposed resolution (§1):** [`ADR-0011-employee-archive-semantics.md`](adr/ADR-0011-employee-archive-semantics.md)
— canonical model: `employees.is_archived` + `employment_types.archives_record`
with system seed `code = dismissed`.

---

## 1. Employment type identity and archive semantics

### 1.1 Executive summary

The user's concern is **confirmed**: employment type **«Уволен»** (`code = dismissed`) is
**not** seeded in the schema. Archive logic depends on `get_by_code("dismissed")`, which
silently no-ops when the row is absent. The three concerns — **identity**, **display name**,
and **archive semantics** — are conflated in documentation and partially in code.

| Concern | Current mechanism | Stable across restarts? | Stable on fresh DB? | Stable across sync/import? |
| --- | --- | --- | --- | --- |
| Identity (FK) | `employment_types.id` (INTEGER PK) | Yes (same DB) | Only for migration seeds 1–3 | No (sync sends raw integer) |
| Semantic identity | `employment_types.code` (UNIQUE, immutable after create) | Yes | Only if row exists with that code | Import: yes (code alias); sync: not used |
| Display name | `employment_types.name` (admin-renamable) | Yes but editable | No (admin/localized) | Import/export by name |
| Archive trigger | Hard-coded lookup `code = 'dismissed'` | Yes if row exists | **No — row not seeded** | N/A (types not synced) |

### 1.2 Schema definition

Table `employment_types` (migration `0001_initial_schema.sql`):

```sql
CREATE TABLE employment_types (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

| Field | Role | Notes |
| --- | --- | --- |
| `id` | Surrogate FK on `employees.employment_type_id` | Auto-increment for admin-created rows; explicit for seeds |
| `code` | Stable machine identifier | UNIQUE; set at create; **no rename API** |
| `name` | Human display label | Editable via `rename_employment_type()` |
| `is_archived` | Directory soft-delete | Hides from `active_only` lists; does **not** archive employees |

**Absent compared to org-structure directories (ADR-0010):** `external_id` (UUID), any
semantic flag such as `archives_record`.

Record type: `EmploymentTypeRecord` in `src/data/directories.py`.

### 1.3 Default seeding

Migration `0001` inserts exactly **three** employment types with **fixed IDs**:

| id | code | name |
| --- | --- | --- |
| 1 | `staff` | Штатный |
| 2 | `temporary` | Временный |
| 3 | `contractor` | Подрядчик |

**`dismissed` / «Уволен» is not seeded.** No later migration adds it.

Migration `0016_remove_inactive_status.sql` deletes availability status `inactive`
(«Уволен / неактивен») and comments that dismissal should use employment type code
`dismissed` — but the migration performs **only the DELETE**, not an INSERT for
`dismissed`.

Technical specification §3.1 lists only Штатный / Временный / Подрядчик as employment
types; §3.9 still references «Уволен» as an archive **trigger** without specifying whether
that is a status or an employment type.

### 1.4 Is «Уволен» created automatically?

**No.** Bootstrap and migrations do not create it. The only creation path is:

1. Administrator → Справочники → Типы занятости → Создать (code + name), via
   `DirectoryService.create_employment_type()`.
2. Test helpers that INSERT directly (e.g. `_ensure_dismissed_employment_type` in
   `tests/integration/test_employee_archive.py`).

On a fresh database after all migrations, `SELECT * FROM employment_types WHERE code = 'dismissed'`
returns **no rows**.

### 1.5 Administrator capabilities

| Action | Supported? | Implementation |
| --- | --- | --- |
| Create arbitrary types (code + name) | Yes | `create_employment_type()` — code lowercased/stripped |
| Rename display name | Yes | `rename_employment_type()` — code unchanged |
| Rename code | **No** | No service method or UI |
| Archive directory entry | Yes | `archive_employment_type()` — `is_archived = 1` |
| Restore directory entry | Yes | `unarchive_employment_type()` |
| Hard delete | **No** | Archive-only, same as other directories |
| Create duplicate codes | **No** | UNIQUE constraint + service check |
| Create multiple types with same display name | **Yes** | No uniqueness on `name` |

Archiving an employment **type** does not archive employees holding that type.

### 1.6 Import and export identification

**Export** (`EmployeeExportService`): writes the employment type **display name**
(`name` by `employment_type_id`). Code is not exported.

**Import** (`EmployeeImportService._catalog()`): builds a casefolded lookup from:

1. `name` → `id` for all active types
2. `code` → `id` as a secondary alias (`setdefault` on the same dict)

Import row evaluation (`domain/employee_import.py`) resolves `employment_type` column via
this combined index. Duplicate names (case-insensitive) are dropped from the index and
cause resolution failure.

**Implication:** import can match by code even when the column header says «Тип занятости»
and the cell contains `dismissed`, but export round-trips by **name only**.

### 1.7 Synchronization identification

ADR-0010 and `domain/directory_sync.py` **deliberately exclude** `employment_types` from
`SYNCED_TABLES`. Branch sync packages carry employees with a raw `employment_type_id`
integer:

```python
# src/services/directory_sync.py (employee export row)
"employment_type_id": row.employment_type_id,
```

Comment in that file states types are «fixed system seeds … ids 1–3 … identical across
every installation». That assumption is **partially true** (only for the three seeded
types) and **false** for any admin-created type including `dismissed`.

Cross-installation identity for employment types is therefore **undefined** in the sync
protocol: receivers must already have matching numeric IDs, which is only reliable for
seeded rows 1–3 on fresh databases.

### 1.8 Code that assumes specific identity

| Location | Assumption | Risk |
| --- | --- | --- |
| `src/services/employees.py` `archive_employee()` | `get_by_code("dismissed")` | Archive succeeds but **does not** set dismissal type if row missing |
| `src/services/standard_reports.py` `_temporary()` | `code == "temporary"` | Report empty/wrong if seed missing or code renamed at DB level |
| `src/services/directory_sync.py` | `employment_type_id` portable across peers | Breaks for id ≠ 1–3 or reordered seeds |
| `src/domain/reports.py` | `TEMPORARY_EMPLOYMENT_CODE = "temporary"` | Same as reports |
| Tests (many) | `employment_type_id=1` | Assumes `staff` remains id 1 |
| `src/services/status_history.py` | `INACTIVE_STATUS_CODE = "inactive"` | **Dead path** after migration 0016 |
| `src/domain/reports.py` | `ABSENCE_STATUS_CODES` includes `"inactive"` | Stale; status removed |
| `docs/manual/user-guide.md` §4 | Inactive **status** triggers archive | **Stale** — archive no longer via status |
| `docs/ROADMAP.md` EPIC-014 | Archive via «Уволен/неактивен» **status** | **Stale** — rework moved to employment type |

No code matches the Russian display name «Уволен». The archive path uses **code**
`dismissed`, not name.

### 1.9 Three concerns — separated

#### Identity (which directory entry)

- **Primary within one database:** `id` (FK).
- **Semantic / machine identity:** `code` — unique, immutable after creation, intended for
  logic such as reports and archive (same pattern as `availability_statuses.code` and
  `roles.code`).
- **Not used:** UUID / `external_id`.
- **Unreliable as identity:** display `name`; numeric `id` across installations.

#### Display name (what users see)

- `name` — fully admin-controlled, localizable.
- Shown in UI combos, export files, report markers (`employee.employment_type` → name).
- Must not be used for archive or report semantics.

#### Archive semantics (employee → archive)

Currently implemented as **two independent effects** in `archive_employee()`:

1. If `code = dismissed` exists → set `employment_type_id` to that row's `id`.
2. Always → set `employees.is_archived = 1`.

Employee archive is **`employees.is_archived`**, not `employment_types.is_archived`.
Selecting a «dismissed» type in the employee card does **not** auto-archive; only the
explicit archive action does.

There is **no** `archives_record` (or equivalent) column. Archive semantics are implied
only by the hard-coded code string `dismissed`.

### 1.10 Critical question — reliable identifier matrix

| Scenario | Reliable identifier | Notes |
| --- | --- | --- |
| Application restart (same DB) | `id`, `code` | Both persist |
| Fresh DB creation | `code` for seeds `staff`/`temporary`/`contractor` only | Fixed ids 1–3; **`dismissed` absent** |
| XLSX import | `name` or `code` (case-insensitive) | Export uses name only |
| XLSX export | `name` | Loses code unless name encodes it |
| Branch sync | `employment_type_id` integer | Safe only for identical seed state (1–3) |
| Administrator renames «Уволен» → «Уволенный» | `code` still `dismissed` | Archive logic unaffected |
| Administrator creates type named «Уволен» with code `fired` | **No link to archive** | Name coincidence irrelevant |
| Administrator archives `dismissed` type | `get_by_code` still finds row | Archive type assignment still works; type hidden from new assignments |

**Do not use** display name «Уволен» as an identifier. **Do not assume** `dismissed` exists
on fresh DB. **Do not assume** numeric id 4 (or any fixed id) for dismissal across
installations unless seeded by migration.

### 1.11 Archive-specific domain-model evaluation

The archive rework (migration 0016 + `archive_employee` change) moved dismissal from
**availability status** `inactive` to **employment type** `dismissed`, but only completed
half the migration:

- Removed old status ✓
- Added seed for `dismissed` ✗
- Added explicit semantic property ✗
- Updated all documentation ✗

#### Option A — Seed system type `dismissed` (extend 0016 or new migration)

Insert `(4, 'dismissed', 'Уволен', …)` with fixed id, same pattern as `staff`/`temporary`/
`contractor`. Archive logic keeps `get_by_code("dismissed")`.

- Pros: minimal code change; aligns with existing `code`-based report for `temporary`;
  stable id on every fresh DB; matches `directory_sync` assumption for id 1–3 extended to 4.
- Cons: display name still editable; admin could archive the type; code is still a magic
  string in application code.

#### Option B — Semantic flag `archives_record` on `employment_types`

Add `archives_record INTEGER NOT NULL DEFAULT 0`. Archive looks up
`WHERE archives_record = 1` (exactly one enforced). Identity for logic is the flag, not a
code string.

- Pros: separates archive semantics from HR taxonomy; admin can rename freely; multiple
  employment types possible without hard-coded codes.
- Cons: schema + UI + migration; need invariant (at most one, or clarify many); sync/import
  must agree on semantics (exclude from sync or carry code/flag).

#### Option C — Archive independent of employment type

Archive only toggles `employees.is_archived`; employment type unchanged (or set manually).

- Pros: simplest semantics; no dismissal type required.
- Contradicts current implementation and tester rework direction.

#### Recommendation (domain model, not implementation)

1. **Treat `code` as the canonical semantic identity** for system employment types, matching
   `availability_statuses` and `roles`. Do not match on `name`.
2. **Guarantee the archiving type exists on every fresh DB** — either seed `dismissed` in
   migrations (Option A) or introduce `archives_record` (Option B). The current state
   (comment without seed) is a defect.
3. **Keep `employees.is_archived` as the authoritative archive flag**; employment type
   assignment on archive is metadata, not the archive mechanism itself.
4. **Do not rely on numeric `employment_type_id` in sync** without either (a) excluding it
   and mapping by `code` at import, or (b) adding `employment_types` to sync with stable
   `code` as reconcile key.
5. If Option B is chosen, `archives_record` answers «which type means dismissed for
   reporting» without coupling to a Russian label or a specific integer id.

### 1.12 Stale artifacts to reconcile (any fix)

- `docs/manual/user-guide.md` — archive via inactive status
- `docs/ROADMAP.md` EPIC-006 / EPIC-014 — status-based dismissal
- `src/services/status_history.py` — `INACTIVE_STATUS_CODE` dead code
- `src/domain/reports.py` — `inactive` in `ABSENCE_STATUS_CODES`
- `tests/unit/test_branch_summary_report.py` — asserts `is_absent_status("inactive")`
- Migration 0016 comment vs missing INSERT

---

## Appendix — evidence index

| Topic | Primary files |
| --- | --- |
| Schema + seeds | `src/data/migrations/0001_initial_schema.sql`, `0016_remove_inactive_status.sql` |
| Repository | `src/data/directories.py` (`EmploymentTypeRepository`) |
| Directory CRUD | `src/services/directories.py`, `src/ui/directories_dialog.py` |
| Archive logic | `src/services/employees.py`, `tests/integration/test_employee_archive.py` |
| Import/export | `src/services/employee_import.py`, `src/domain/employee_import.py`, `src/services/employee_export.py` |
| Sync exclusion | `src/domain/directory_sync.py`, `src/services/directory_sync.py`, `docs/adr/ADR-0010-directory-identity-and-sync.md` |
| Reports by code | `src/services/standard_reports.py`, `src/domain/reports.py` |
