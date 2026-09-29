# Production-readiness technical debt audit

**Status:** discovery complete (no remediation in this change)  
**Branch:** `cursor/production-readiness-audit-2274`  
**Base:** `origin/master` @ `f8095bf` (2026-09-29)  
**Scope:** evidence gathering for production-blocking risks across runtime, persistence, security, operations, transport/conversion workflows, packaging, and test confidence.

Governance: `docs/ANCHOR_PROTOCOL.md`, `docs/ANCHOR_CORE.md`, existing ADR/EPIC conventions. This document does not replace ADRs; it records audit findings and proposed backlog items.

---

## Executive summary

**Assessment (evidence-based):** Core offline HR workflows (auth, roster, employee card, statuses, standard/template reports, spreadsheet import/export, backup/restore, migrations, encryption) show strong automated coverage (771 tests passing locally; 380 acceptance-marked tests passing). **Safe production use of the full product scope—including EPIC-020/021 transport exchange assigned to HR—is not supported by the current permission model and operator UI surface.**

| Severity | Count |
|----------|------:|
| P0 — Production blocker | 1 |
| P1 — High production risk | 4 |
| P2 — Significant debt | 8 |
| P3 — Non-blocking debt | 5 |

**Attention before production (if Mechanism 2 / unified DB dialog is in scope):**

1. **PR-AUD-001 (P0):** HR users see «Импорт данных» but cannot complete transport validate/apply (`MANAGE_ENCRYPTION_KEYS` gate inside directory sync planning).
2. **PR-AUD-002 (P1):** No shipped UI for transport **export** or transport **key/trust** administration; Mechanism 2 is service-tested only (`tests/e2e_mechanics/`, integration tests).
3. **PR-AUD-003 (P1):** Production `.deb` launcher forwards `--demo` / `PERSONNEL_AVAILABILITY_DEMO` without guard (fixed credentials, idle lock disabled).
4. **PR-AUD-004 (P1):** EPIC-021 still «В процессе» in `ROADMAP.md`; operator manuals omit transport procedures.

**Insufficient evidence / out of audit scope:** Real customer `.deb` install on Debian 12 (CI `deb-verify` not re-run in this VM); long-horizon multi-process SQLite contention under two simultaneous GUI instances (inferred risk only).

---

## Production surface map

### Entry points

| Entry | Location | Notes |
|-------|----------|--------|
| GUI main | `personnel-availability` → `ui.app:main` (`pyproject.toml` `[project.scripts]`) | `--demo`, `--db` CLI flags |
| Packaged launcher | `packaging/debian/personnel-availability-launcher` | `exec … personnel-availability "$@"` |
| DB startup | `ui.app.run` → `prepare_database_startup` → login → `UpgradeService.apply_pending` | Corruption recovery in `data/backup_io.py` |

### Critical workflows (persistent writes)

- Bootstrap / recovery: `services/bootstrap.py`, `services/authentication.py`
- Accounts / security: `services/account_management.py`
- Employees / directories / statuses: `services/employees.py`, `services/directories.py`, `services/status_history.py`
- Import/export (spreadsheet): `services/employee_import.py`, `services/employee_export.py`, `ui/import_export_dialog.py`
- Conversion (EPIC-018): `services/employee_conversion.py`, `ui/conversion_wizard_flow.py`, `DatabaseOperationsDialog`
- Transport (EPIC-020): receive `services/transport_receive.py`, validate `services/transport_import_validation.py`, apply `services/transport_import_apply.py`, export `services/transport_export.py`, keys `services/transport_key_admin.py`, UI import only `ui/transport_import_dialog.py`
- Backup/restore: `services/backup.py`, `ui/backup_dialog.py` / EPIC-021 tab
- Reports / templates: `services/standard_reports.py`, `services/template_library.py`, `reports/*`
- Audit: `services/user_action_log.py`, append-only repos (`tests/integration/test_repositories_append_only.py`)

### Persistence

- SQLCipher single file + `.keywrap` sidecar (`data/db.py`, `data/keywrap.py`, ADR-0002/0003)
- Versioned migrations `data/migrations/*.sql`, `data/migrations.py` (transactional apply)
- FK enforcement: `PRAGMA foreign_keys = ON` on connect (`data/db.py`)

### External dependencies

- Runtime: PySide6, sqlcipher3, argon2-cffi, cryptography, openpyxl, reportlab, pypdf (`pyproject.toml`)
- **No network calls in `src/`** (offline invariant A4 confirmed by grep)
- Deploy target: Debian 12 `.deb` (`packaging/`, CI `deb-build` / `deb-verify`)

### Operational dependencies

- Administrator for backup restore, account management, template upload, transport trust bootstrap (intended)
- Weekly backup per `docs/manual/maintenance-runbook.md`
- Pre-upgrade backup via `UpgradeService`

---

## Findings summary table

| ID | Sev | Title |
|----|-----|--------|
| PR-AUD-001 | P0 | HR transport import blocked after UI exposes tab |
| PR-AUD-002 | P1 | Transport export and key/trust admin not in UI |
| PR-AUD-003 | P1 | Demo mode enabled via production launcher |
| PR-AUD-004 | P1 | EPIC-021 incomplete; manuals omit transport ops |
| PR-AUD-005 | P1 | Observer may mutate statuses (ADR-0015 vs ТЗ) |
| PR-AUD-006 | P2 | Bootstrap commits DB before keywrap file written |
| PR-AUD-007 | P2 | Backup restore failure path reconnects without operator rollback guidance |
| PR-AUD-008 | P2 | Upgrade «migration failed and rollback failed» edge case |
| PR-AUD-009 | P2 | Conversion bulk apply commits per row (partial success) |
| PR-AUD-010 | P2 | No single-instance / DB file lock for concurrent processes |
| PR-AUD-011 | P2 | Transport apply skips status history payload (documented no-op) |
| PR-AUD-012 | P2 | Template reports: no runtime marker values (documented limitation) |
| PR-AUD-013 | P3 | Template validation silent skip for malformed `{{marker}` (#36) |
| PR-AUD-014 | P3 | Stale EPIC-021 placeholder docstring on dialog class |
| PR-AUD-015 | P3 | Alternate conversion wizard helper without bulk gate (test-only import path) |
| PR-AUD-016 | P3 | UI layer `commit()` on conversion session resume |
| PR-AUD-017 | P3 | Action log dialog open relies on service-layer permission only |
| PR-AUD-018 | P3 | `--db` CLI on production entrypoint (test hook) |

---

## P0 / P1 — detailed findings

### PR-AUD-001 — P0 — HR cannot complete transport import validate/apply

| Field | Detail |
|-------|--------|
| **Component** | `services/directory_sync_import.py`, `services/transport_import_validation.py`, `ui/database_operations_dialog.py`, `domain/permissions.py` |
| **Evidence** | EPIC-021: HR sees «Импорт данных» (`database_operations_tab_visibility`, `docs/ROADMAP.md` L647–648). ADR-0007 §Права: `IMPORT_EXPORT` — подготовка и приём transport packages — **HR**. `TransportImportValidationService.validate_package` calls `DirectorySyncImportService.build_directory_plan` (`transport_import_validation.py` ~L112). `build_directory_plan` calls `_require_transport_admin()` requiring `Permission.MANAGE_ENCRYPTION_KEYS` (`directory_sync_import.py` L159–161, L235–237). HR role has `IMPORT_EXPORT` but not `MANAGE_ENCRYPTION_KEYS` (`permissions.py` L63–77). **Reproduced locally:** `AuthorizationError: permission denied: manage_encryption_keys` for HR; admin succeeds (audit command in §Evidence and verification). |
| **Failure scenario** | HR opens «Работа с базой данных» → «Импорт данных» → selects package → crypto receive may succeed → validation/plan step fails authorization. Apply path also uses directory sync with same gate (`transport_import_apply.py` via `apply_directory_plan(..., commit=False)`). |
| **Production impact** | Branch sync import cannot be operated by the role explicitly assigned the import tab; only Administrator can complete flow—contradicts ROADMAP/ADR unless operations are admin-only by undocumented exception. |
| **Confidence** | high |
| **Root cause** | Permission split in ADR-0007 not reflected in `DirectorySyncImportService` gate (uses admin-only permission for plan/build/apply). |
| **Remediation direction** | ADR likely required if changing permission model: either gate plan/apply on `IMPORT_EXPORT` for read-only planning + apply orchestrator, or restrict import tab to Administrator and update ROADMAP/manuals. Add integration test: HR receive → validate → apply. |
| **Scope** | medium |
| **ADR** | yes |
| **EPIC** | yes (EPIC-021 / transport permissions) |

### PR-AUD-002 — P1 — No UI for transport export or key/trust administration

| Field | Detail |
|-------|--------|
| **Component** | `services/transport_export.py`, `services/transport_key_admin.py`, `src/ui/*` |
| **Evidence** | Grep: no `TransportExport` / `transport_export` under `src/ui/`. `TransportKeyAdminService` only referenced from services/tests/e2e (`tests/e2e_mechanics/peer.py`). EPIC-020 marked ✅ in `ROADMAP.md`; ADR-0007 states UI bootstrap/trust is implementation. |
| **Failure scenario** | Administrator must export encrypted packages and configure peer trust to enable Mechanism 2; without UI or documented CLI, production relies on undeclared tooling (e2e harness only). |
| **Production impact** | End-to-end encrypted exchange not operable by documented manual procedures; import-only UI is insufficient for duplex sync. |
| **Confidence** | high |
| **Remediation direction** | EPIC for export + key/trust UI (or formal runbook using supported admin tooling); UI smoke tests. |
| **Scope** | large |
| **ADR** | no (unless UX/security workflow changes) |
| **EPIC** | yes |

### PR-AUD-003 — P1 — Demo mode reachable in production package

| Field | Detail |
|-------|--------|
| **Component** | `ui/app.py`, `services/demo.py`, `packaging/debian/personnel-availability-launcher` |
| **Evidence** | `--demo` and `PERSONNEL_AVAILABILITY_DEMO` (`app.py` L33–55, L101–122). Credentials `demo`/`demo` (`demo.py` L29–30). `_disable_demo_idle_lock` (`demo.py` L381–392, L456). Launcher passes `"$@"` unchanged. |
| **Failure scenario** | Shortcut/desktop or systemd unit passes `--demo`; or env var set globally → auto-login weak creds, no idle lock, synthetic data presented without technical skill to distinguish from production DB path (`demo_data_dir()` under temp). |
| **Production impact** | Security/policy violation on shared machines; mistaken operational use. |
| **Confidence** | high |
| **Remediation direction** | Strip or gate demo in release builds; document; packaging test asserting prod entry rejects demo flags. |
| **Scope** | small |
| **ADR** | unclear |
| **EPIC** | no (packaging/release policy) |

### PR-AUD-004 — P1 — EPIC-021 incomplete; operator docs gap for transport

| Field | Detail |
|-------|--------|
| **Component** | `docs/ROADMAP.md`, `docs/manual/*` |
| **Evidence** | ROADMAP L36: EPIC-021 «🚧 В процессе». Manuals document backup move to 💾 dialog (`administrator-guide.md`, `maintenance-runbook.md`) but **no** transport import/export/trust procedures (grep transport/hrpkg in `docs/manual/` — empty). |
| **Failure scenario** | Production rollout assumes EPIC-020 operational; admins lack runbook; HR assumes import tab is complete per EPIC-021 text. |
| **Production impact** | Operational errors, false sign-off on «complete» epics. |
| **Confidence** | high |
| **Remediation direction** | Close EPIC-021 with DoD (manuals + functional gates); add transport runbook or defer Mechanism 2 from production scope explicitly. |
| **Scope** | medium |
| **ADR** | no |
| **EPIC** | yes (EPIC-021 closeout) |

### PR-AUD-005 — P1 — Observer can assign statuses (policy deviation)

| Field | Detail |
|-------|--------|
| **Component** | `domain/permissions.py`, ADR-0015 |
| **Evidence** | `_OBSERVER` includes `MANAGE_STATUSES` (L52–60). ADR-0015 documents intentional deviation from ТЗ §4.1 read-only observer. |
| **Failure scenario** | Deployments expecting strict ТЗ observer semantics grant status-write capability. |
| **Production impact** | Authorization/policy mismatch with customer contract unless ADR-0015 explicitly accepted in deployment sign-off. |
| **Confidence** | high (behavior confirmed; impact depends on contract) |
| **Remediation direction** | Deployment checklist acknowledging ADR-0015; no code change required if ADR stands. |
| **Scope** | small (governance) |
| **ADR** | already exists |
| **EPIC** | no |

---

## P2 / P3 — concise entries

### PR-AUD-006 — P2 — Bootstrap DB commit before keywrap persistence

`BootstrapService.initial_administrator_setup`: `conn.commit()` then `save_keywrap(...)` (`bootstrap.py` L101–109). Crash between → DB exists, `needs_setup()` / keywrap missing. No failure-injection test.

### PR-AUD-007 — P2 — Backup restore exception handler

On restore failure after `swap_live_from_backup`, `backup.py` L123–129 opens new connection and logs failure; operator must use runbook/pre-restore files. Partial swap mitigated in `backup_io.swap_live_from_backup` rollback.

### PR-AUD-008 — P2 — Upgrade rollback failure

`UpgradeService.apply_pending` raises `UpgradeError("migration failed and rollback failed: ...")` if rollback fails (`upgrade.py` L99–107). Success rollback tested (`test_safe_upgrade.py`); double-failure untested.

### PR-AUD-009 — P2 — Conversion bulk partial commits

`EmployeeConversionService.save_rows_bulk` commits per successful `save_row`; failures collected (`employee_conversion.py` L90–129). Pre-conversion backup once per service instance (`_ensure_pre_conversion_backup`).

### PR-AUD-010 — P2 — Concurrent GUI / SQLite

`data/db.py` uses default `sqlcipher.connect` without documented single-instance lock; ТЗ A5 assumes sequential users on one laptop, not enforced in code. Inferred corruption/lock risk if two processes open same `personnel.db`.

### PR-AUD-011 — P2 — Status history not applied from transport payload

`TransportImportApplyService._apply_status_history_from_payload` no-op (`transport_import_apply.py` L171–174). Documented in ADR/ROADMAP as out of scope; operators must not expect status history sync.

### PR-AUD-012 — P2 — Template reports without scalar/row input UI

`user-guide.md` §7; EPIC-016 sign-off notes empty markers by design. Not a defect but production limitation for custom templates needing runtime parameters.

### PR-AUD-013 — P3 — Malformed marker typo bypasses validation

EPIC-016 sign-off / issue #36: `{{должность}` not matched by `MARKER_RE`; validation silent; appears literally in output.

### PR-AUD-014 — P3 — Stale docstring on `DatabaseOperationsDialog`

Class docstring says transport-import «placeholder» (`database_operations_dialog.py` L51) while `TransportImportPanel` is wired (L132–144).

### PR-AUD-015 — P3 — Duplicate `run_conversion_wizard_flow` in `conversion_wizard_dialog.py`

Bulk review gate bypass in alternate module; production path uses `conversion_wizard_flow.py` from `database_operations_dialog.py`.

### PR-AUD-016 — P3 — UI commits after session resume

`conversion_wizard_flow.py` touches session + `conn.commit()` in UI layer.

### PR-AUD-017 — P3 — Action log button visibility vs open check

`main_window.py`: button gated by permission; `_open_action_log` relies on unlock; `UserActionLogService` enforces `VIEW_USER_ACTION_LOG`.

### PR-AUD-018 — P3 — `--db` test hook on production CLI

`app.py` L42–47 — intentional for tests; misuse can point UI at wrong database.

---

## Critical paths reviewed

- [x] Application startup: corruption recovery, migration upgrade, login (`ui/app.py`, `services/upgrade.py`, `data/backup_io.py`)
- [x] Authentication, session lock, recovery (`services/authentication.py`, ADR-0004)
- [x] RBAC matrix and UI gating (`domain/permissions.py`, integration `test_auth_rbac.py`)
- [x] Employee CRUD, archive semantics (ADR-0011, integration employee tests)
- [x] Status assignment, clarification, history append-only
- [x] Spreadsheet import/export and reconciliation (ADR-0006)
- [x] Conversion wizard + bulk apply (EPIC-018, ADR-0012)
- [x] Transport receive → validate → apply (EPIC-020; **HR path failed in manual repro**)
- [x] Backup create/restore and pre-apply backups (ADR-0014)
- [x] Standard and template reports
- [x] Packaging/CI assumptions (read `.github/workflows/ci.yml`, `packaging/README.md`)
- [x] Demo mode entry
- [x] Logging redaction (`ui/logging_config.py`)

---

## Evidence and verification

### Commands executed (audit VM, 2026-09-29)

| Command | Result |
|---------|--------|
| `git fetch --all --prune` | OK |
| `ruff check src tests` | All checks passed |
| `mypy src` | Success: 115 files |
| `QT_QPA_PLATFORM=offscreen pytest -q --tb=no` | **771 passed**, 1 failed (see limitation) |
| `QT_QPA_PLATFORM=offscreen pytest -m acceptance -q` | **380 passed** |
| HR `build_directory_plan` repro (inline Python, `PYTHONPATH=src`) | `AuthorizationError: manage_encryption_keys` for HR; admin OK |
| `python3 -m pip_audit` (environment scan) | urllib3/wheel advisories on **tooling/env**, not pinned app deps in `pyproject.toml` |

### Test failure limitation

`tests/unit/test_packaging_smoke.py::test_migrations_discoverable_from_built_wheel` failed: `python3-venv` not installed on audit VM (`ensurepip` unavailable). CI installs full Qt/venv context (`.github/workflows/ci.yml`). **Not classified as product defect.**

### CI not re-executed here

`deb-build`, `deb-verify`, offline Docker smoke — assumed green on `origin/master` from pipeline history; not re-run in this audit turn.

### Key files inspected

Governance: `ANCHOR_PROTOCOL.md`, `ANCHOR_CORE.md`, `ROADMAP.md`, `TESTING.md`, `ARCHITECTURE_AUDIT.md`, ADRs 0004–0015, `acceptance/EPIC-016-signoff.md`  
Core: `src/data/db.py`, `migrations.py`, `backup_io.py`, `services/backup.py`, `upgrade.py`, `bootstrap.py`, transport/conversion services, `ui/app.py`, `database_operations_dialog.py`, `transport_import_dialog.py`  
Packaging: `packaging/debian/personnel-availability-launcher`, `pyproject.toml`, `.github/workflows/ci.yml`

---

## Remediation backlog (proposals only — not implemented)

| Item | Problem | Intended outcome | Area | Dependencies | ADR | EPIC |
|------|---------|------------------|------|--------------|-----|------|
| RB-001 | PR-AUD-001 | HR (or ROADMAP) aligned with transport validate/apply permissions | `directory_sync_import`, validation, tests | ADR-0007 permission model decision | yes | yes |
| RB-002 | PR-AUD-002 | Operator UI for export + key/trust | new UI + manuals | EPIC-019 store | unclear | yes |
| RB-003 | PR-AUD-003 | Demo disabled/gated in release builds | packaging, `app.py` | release policy | unclear | no |
| RB-004 | PR-AUD-004 | EPIC-021 closeout + transport runbook | docs, ROADMAP | RB-001, RB-002 | no | yes |
| RB-005 | PR-AUD-006 | Atomic bootstrap DB+keywrap | `bootstrap.py` | none | no | no |
| RB-006 | PR-AUD-007–008 | Harden restore/upgrade failure UX and tests | backup, upgrade | none | no | no |
| RB-007 | PR-AUD-009 | Bulk conversion transactional semantics or explicit UX | `employee_conversion.py` | ADR-0012 | unclear | optional |
| RB-008 | PR-AUD-010 | Single-instance lock or documented prohibition | `app.py` / `db.py` | A5 interpretation | yes if enforced | optional |
| RB-009 | PR-AUD-013 | Stricter template marker validation | `reports/excel_template.py` | #36 | no | no |

---

## Explicit non-findings

- **Offline/network:** No HTTP client usage in `src/`; CI offline smoke exists for installed `.deb`.
- **Password storage:** Argon2 hashing; integration tests for auth/recovery (`test_auth_rbac.py`, `test_encryption.py`).
- **Migration atomicity:** Transactional migration scripts (`data/sql_script.py`, `migrations.py`); integration `test_migrations.py`, `test_safe_upgrade.py`.
- **Foreign keys:** Enabled on connect; `test_foreign_keys.py`.
- **Audit append-only:** `test_repositories_append_only.py`, `test_user_action_log.py`.
- **Pre-apply auto-backup:** ADR-0014 integration `test_pre_apply_auto_backup.py`.
- **Transport apply atomicity (admin path):** `test_transport_import_apply.py` with administrator session.
- **Sensitive field permissions:** Reserved in matrix; `test_sensitive_fields.py`.
- **Core HR UI acceptance:** EPIC-016 sign-off paths documented with automated evidence.

---

## ADR notes (audit-triggered, not authored here)

| Finding | Why ADR may be needed |
|---------|------------------------|
| PR-AUD-001 | Changes effective permission model for directory sync / transport (ТЗ §4.1 / ADR-0007 §Права) |
| PR-AUD-008 / RB-008 | Single-instance enforcement touches A5 operational model |
| PR-AUD-003 | If demo is removed from production artifact — release/security policy |

No new ADR file was added in this audit branch (discovery only).

---

## Hard stops

None. Classification of PR-AUD-001 permission mismatch is confident; human decision required on **intended** operator role for transport (HR vs Administrator only) before implementation.
