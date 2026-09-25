# ADR-0010 Addendum — 020-D Validation Gate Reuses the Reconciliation Core, Split from Apply

Статус: Предложено
Дата: 2026-09-25
Автор: Cursor (draft from human architectural decision); awaiting acceptance
Затронутый EPIC: EPIC-020 (slices 020-D / 020-E); relates to EPIC-026 / ADR-0010
Relates to: ADR-0010 (directory/employee identity & sync), ADR-0007 v3 (transport)

## Контекст

020-D's spec requires pre-DB validation only — external_id+ФИО matching, no
fuzzy reconcile, no auto conflict resolve, whole-package reject/pend, **no DB
writes, no transport-state advance**. That matching model
(EXACT/CONFLICT/LOW/AMBIGUOUS/NEW) is already built in EPIC-026 Part 4a/4b, but
only one of the two services is actually pure:

- `EmployeeReconciliationService.build_reconciliation` — genuinely read-only
  classification (`Does not write` in its own docstring). Reusable as-is.
- `directory_sync_import.py`'s `apply_package` — **not** read-only: it writes
  inside `SAVEPOINT directory_sync_apply` via `_reconcile_branches/
  departments/divisions/positions` (create/update), then runs the
  broken-employee check, then calls `apply_employees(..., commit=False)`.
  Rollback-on-conflict does not make this a pure validator — the writes still
  happen inside the call.
- `employee_sync_import.py`'s `apply_employees` — also conflates validate +
  write: reconcile → reject-blocking → resolve → `_create_row`/`_update_row`,
  under `SAVEPOINT employee_sync_apply` when `commit=True` (~L88–145).

020-E is specified as the **sole owner** of the DB transaction (business
writes + `StatusHistoryService` + package/replay record + transport-state
advance, all atomic together). Calling either `directory_sync_import.py` or
`employee_sync_import.py` as-is from 020-D would violate 020-D's "no DB
writes" invariant.

## Рассмотренные варианты

1. **Write separate validation logic for 020-D from scratch.** Rejected —
   duplicates ADR-0010's matching rules in a second place, inviting drift.
2. **Call the existing `apply_package`/`apply_employees` as-is from 020-D and
   accept early writes.** Rejected — breaks 020-D's explicit
   no-writes/no-transport-advance invariant for *both* directories and
   employees, not just employees as an earlier draft assumed.
3. **Split employees only, leave directories as a single
   write-then-rollback-on-conflict call inside 020-D.** Rejected — 020-D would
   still be performing writes (even if rolled back on conflict), which is a
   real deviation from "no DB writes" regardless of whether they're committed.
4. **Split both directory and employee import into plan/apply pairs; 020-D
   calls only plan builders.** Chosen — see Решение.

## Решение

Reuse `EmployeeReconciliationService.build_reconciliation` directly in 020-D,
unchanged.

Split **both** `directory_sync_import.py` and `employee_sync_import.py` into
plan/apply pairs:

1. **`build_directory_plan(...)`** — pure, no writes: runs the existing
   `_reconcile_*` matching logic against a **projected state** (in-memory
   diff of incoming vs. current rows, not a DB write) to produce a plan of
   directory creates/updates, plus a breakage preview for any employee an
   update would affect. No savepoint, no commit.
2. **`apply_directory_plan(plan, conn)`** — takes an already-validated plan
   and performs the writes; the `SAVEPOINT directory_sync_apply` moves here,
   used only as an internal atomicity aid inside `apply_plan`, never exposed
   to 020-D.
3. **`build_employee_plan(...)`** — pure, no writes: same idea, wraps
   `build_reconciliation` and produces an explicit plan (creates/updates/
   archives + any `ConfirmationRequiredError`s).
4. **`apply_employee_plan(plan, conn)`** — performs the writes; the existing
   `SAVEPOINT employee_sync_apply` moves here, called *only* by 020-E's
   orchestrator inside its single transaction, participating in the caller's
   transaction rather than opening its own.

020-D calls only `build_directory_plan` then `build_employee_plan` (directory
plan first, per the fixed processing order). Any invalid row, breakage, or
`ConfirmationRequiredError` in either plan means 020-D stops there and rejects
or pends the whole package — no plan is handed to 020-E.

## Последствия

- No new reconciliation / matching rules are written; ADR-0010's matching
  semantics stay in one place for both directories and employees.
- 020-D and 020-E get a clean seam: validation produces two plans
  (directory, employee), apply consumes them in order inside one transaction.
- Both services' internal SAVEPOINT usage is retired from the "validate" path
  in favor of caller-owned transactions (020-E) — the same layering fix
  applies to directories as to employees.
- File-based EPIC-026 import (Part 4a/4b, still used for offline package
  exchange) keeps working against the same plan/apply APIs — one code path
  instead of two, for both directories and employees.
- Breakage detection for directories moves from post-write-in-savepoint to a
  projected-state simulation in `build_directory_plan` — this is new logic,
  not a reuse, and needs its own tests (breakage cases where an update would
  orphan an employee's org assignment, computed without writing anything).

## Как проверяется

| Тест / проверка | Что подтверждает |
|---|---|
| Existing `tests/integration/test_adr0010_*.py` (sync import/export/reconcile) remain green after refactor | File-based Part 4a/4b still works via plan→apply |
| New: `build_directory_plan` breakage preview without DB writes | Projected-state orphan/breakage cases; `PRAGMA`/row counts unchanged after plan-only call |
| New: `build_employee_plan` emits CONFLICT/LOW/AMBIGUOUS/NEW/EXACT without writes | Same classification semantics as `build_reconciliation` |
| 020-D (when implemented) calls only plan builders | No transport-state advance; no business writes on reject/pend |
| 020-E (when implemented) is sole caller of `apply_*_plan` inside one transaction | SAVEPOINTs not used on the 020-D path |

## История

| Версия | Дата | Суть |
|---|---|---|
| draft-1 | 2026-09-25 | Employees-only split; incorrectly described Part 4a as read-only until apply |
| draft-2 (this file) | 2026-09-25 | Both directory and employee plan/apply; projected-state breakage; Status: Предложено |
