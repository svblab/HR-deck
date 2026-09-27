# E2E Mechanics Validation (Transport + Conversion + Requires-attention)

Headless, service-layer-only scenario for two independent peer installations
(**Branch A** / **Branch B**). No GUI, no Qt event loop, no browser automation.

## What it validates

1. Bootstrap + out-of-band mutual transport trust (public keys read via SQL inside
   the harness only — no new product API).
2. Full backup immediately after bootstrap/trust; restore at the end to the exact
   post-bootstrap snapshot (business + transport state).
3. Timed duplex transport exchange (`DirectorySyncService` → encrypted package →
   `TransportInboundImportService`) via a **shared volume** only.
4. Exactly one irreversibly corrupted package: crypto rejection, no business
   writes, transport state not advanced (then the good original is applied so
   sequences stay aligned). Note: product `record_package_rejection` is not
   wired; the harness asserts unchanged snapshots instead of inventing audit rows.
5. EPIC-018 conversion: ingest incomplete rows, FIO collision → skip (no auto-link),
   otherwise save.
6. EPIC-007 «Requires attention»: raise (expired status) and clear (new assignment)
   on each peer locally (status history is not transported).
7. Any `PENDING_CONFIRMATION` / non-automatic import disposition → **hard fail**.

## Reproducibility

| Flag | Default | Meaning |
|------|---------|---------|
| `--seed` | `20260927` | RNG seed for all random decisions |
| `--duration-seconds` | `1440` (~24 min) | Timed loop wall-clock; hard cap **3600** |
| `--root` | `/e2e-data` (Docker) or `._e2e_mechanics` | Peer data + exchange |

## Run with Docker (Ubuntu 24.04)

From the repository root (Docker Desktop running):

```bash
docker compose -f tests/e2e_mechanics/docker-compose.yml build
docker compose -f tests/e2e_mechanics/docker-compose.yml run --rm e2e-runner
```

Shorter smoke (e.g. 3 minutes):

```bash
docker compose -f tests/e2e_mechanics/docker-compose.yml run --rm e2e-runner \
  --duration-seconds 180 --seed 20260927
```

Copy the report out of the named volume:

```bash
docker compose -f tests/e2e_mechanics/docker-compose.yml run --rm --entrypoint cat \
  -v e2e_report:/e2e-data/report e2e-runner /e2e-data/report/report.md
```

Or after a run:

```bash
docker run --rm -v tests_e2e_mechanics_e2e_report:/report alpine \
  cat /report/report.md
```

(Volume name prefix may vary; use `docker volume ls | grep e2e_report`.)

## Run locally (no containers)

```bash
pip install -e ".[dev]"
python -m tests.e2e_mechanics --root ._e2e_mechanics --duration-seconds 180
```

## Interpreting the report

Artifacts under `<root>/report/`:

- `report.json` — machine-readable counters
- `report.md` — human summary
- `scenario.log` — verbose diagnostics

Key fields:

| Field | Meaning |
|-------|---------|
| `success` | Entire scenario including restore verification |
| `exports_a_to_b` / `exports_b_to_a` | Successful transport exports |
| `imports_*_ok` | Imports with `ready_for_apply` |
| `corrupted_package_rejections` | Must be ≥ 1 |
| `conversion_*` | EPIC-018 session/row metrics |
| `clarification_raised` / `cleared` | EPIC-007 raise/clear events |
| `restore_verified` | Both peers match post-bootstrap fingerprints |

Exit code `0` = success; non-zero = failure (`failure_message` + log).

## Implementation notes

- Orchestration is one Ubuntu runner process with **two isolated SQLCipher
  installations** (separate volumes / data dirs). Packages move only through
  the shared `exchange` volume (`network_mode: none`).
- OOB trust: public keys are read via SQL inside the harness (same approach as
  existing transport unit tests). No product identity-bundle API is added.
- `PENDING_CONFIRMATION` is a hard failure; the timed loop never creates
  ambiguous FIO+org pairs across peers.
- UI idle session lock (900s) is disabled on harness sessions so long runs do
  not clear `master_key`.
- Example successful full run (~24 min, seed `20260927`):
  `artifacts/full-24min-report.md`.
