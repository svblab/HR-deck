"""Timed dual-peer mechanics scenario (service layer only)."""

from __future__ import annotations

import logging
import random
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from tests.e2e_mechanics.actions import (
    assign_status_variants,
    create_unique_employee,
    edit_random_employee,
    raise_and_clear_clarification,
    run_conversion_batch,
)
from tests.e2e_mechanics.clock import ScenarioClock
from tests.e2e_mechanics.oob import establish_mutual_trust
from tests.e2e_mechanics.peer import open_peer
from tests.e2e_mechanics.report import ScenarioReport, WallTimer
from tests.e2e_mechanics.transport_exchange import (
    TransportExchangeHardFail,
    assert_unchanged_transport_and_business,
    export_to_file,
    import_from_file,
)

_log = logging.getLogger("e2e_mechanics.scenario")

_ADMIN_PASSWORD = "E2E-Admin-Pass-1"
_MAX_DURATION_CAP = 60 * 60


def run_scenario(
    *,
    root: Path,
    seed: int,
    duration_seconds: int,
) -> ScenarioReport:
    if duration_seconds < 1:
        raise ValueError("duration_seconds must be >= 1")
    if duration_seconds > _MAX_DURATION_CAP:
        raise ValueError(f"duration_seconds must be <= {_MAX_DURATION_CAP}")

    report = ScenarioReport(seed=seed, duration_seconds_target=duration_seconds)
    report.started_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    timer = WallTimer()
    rng = random.Random(seed)

    peer_a_dir = root / "peer-a"
    peer_b_dir = root / "peer-b"
    exchange_dir = root / "exchange"
    work_dir = root / "work"
    for d in (peer_a_dir, peer_b_dir, exchange_dir, work_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Fixed logical start — independent of wall clock; advances slowly during loop.
    clock = ScenarioClock(datetime(2026, 9, 15, 9, 0, 0, tzinfo=UTC))

    peer_a = open_peer(
        label="A",
        data_dir=peer_a_dir,
        clock=clock,
        login="admin_a",
        password=_ADMIN_PASSWORD,
    )
    peer_b = open_peer(
        label="B",
        data_dir=peer_b_dir,
        clock=clock,
        login="admin_b",
        password=_ADMIN_PASSWORD,
    )

    try:
        assert peer_a.key_admin and peer_a.store and peer_b.key_admin and peer_b.store
        dirs_a, dirs_b = establish_mutual_trust(
            admin_a=peer_a.key_admin,
            store_a=peer_a.store,
            conn_a=peer_a.conn,
            admin_b=peer_b.key_admin,
            store_b=peer_b.store,
            conn_b=peer_b.conn,
            label_a="Branch A",
            label_b="Branch B",
        )
        peer_a.directions = dirs_a
        peer_b.directions = dirs_b
        _log.info("mutual trust established directions A=%s B=%s", dirs_a, dirs_b)

        peer_a.ensure_org(branch_name="Branch A HQ")
        peer_b.ensure_org(branch_name="Branch B HQ")

        # Seed a few employees before backup so restore target is non-trivial trust-only?
        # Spec: backup immediately after bootstrap (incl. trust). Org may be empty.
        # Keep post-bootstrap = trust + identities, before business mutations.
        snap_a = peer_a.business_fingerprint()
        snap_b = peer_b.business_fingerprint()
        peer_a._post_bootstrap_snapshot = snap_a
        peer_b._post_bootstrap_snapshot = snap_b

        assert peer_a.backup and peer_b.backup
        peer_a.backup_path = peer_a.backup.create_backup(peer_a_dir / "initial-backup")
        peer_b.backup_path = peer_b.backup.create_backup(peer_b_dir / "initial-backup")
        _log.info("initial backups A=%s B=%s", peer_a.backup_path, peer_b.backup_path)
        report.notes.append(
            f"initial backup A={peer_a.backup_path.name} B={peer_b.backup_path.name}"
        )

        # First business activity after backup.
        for _ in range(3):
            create_unique_employee(peer_a, rng, report)
            create_unique_employee(peer_b, rng, report)

        corrupted_done = False
        tick = 0
        while timer.elapsed() < duration_seconds:
            tick += 1
            actor = peer_a if tick % 2 == 1 else peer_b
            other = peer_b if actor is peer_a else peer_a

            create_unique_employee(actor, rng, report)
            if rng.random() < 0.7:
                edit_random_employee(actor, rng)
            assign_status_variants(actor, rng, report)
            if rng.random() < 0.35:
                raise_and_clear_clarification(actor, rng, report)

            if tick % 4 == 0 or rng.random() < 0.4:
                run_conversion_batch(
                    actor,
                    rng,
                    report,
                    work_dir=work_dir,
                    force_fio_collision=True,
                )

            # Periodic duplex exchange (both directions).
            if tick % 2 == 0 or tick <= 2:
                _exchange(peer_a, peer_b, exchange_dir, report, rng)
                _exchange(peer_b, peer_a, exchange_dir, report, rng)

            # Exactly one intentional corruption (after at least one successful export).
            if (
                not corrupted_done
                and report.exports_a_to_b + report.exports_b_to_a >= 1
                and tick >= 3
            ):
                _corrupt_once(actor, other, exchange_dir, report)
                corrupted_done = True

            # Advance logical clock slowly so date-based clarification stays meaningful.
            if tick % 5 == 0:
                clock.advance(hours=1)

            # Keep sessions alive even if timeout were re-enabled.
            peer_a.session.touch()
            peer_b.session.touch()

            # Pace long runs: ~1 tick / 2s keeps DB size and report stats meaningful.
            if duration_seconds >= 120:
                time.sleep(2.0)
            elif duration_seconds >= 30:
                time.sleep(0.05)

        if not corrupted_done:
            _corrupt_once(peer_a, peer_b, exchange_dir, report)
            corrupted_done = True

        # Final clean exchange both ways.
        _exchange(peer_a, peer_b, exchange_dir, report, rng)
        _exchange(peer_b, peer_a, exchange_dir, report, rng)

        _restore_and_verify(peer_a, snap_a, report)
        _restore_and_verify(peer_b, snap_b, report)
        report.restore_verified = True
        report.success = True
        report.notes.append(f"ticks={tick}")
    except TransportExchangeHardFail as exc:
        report.success = False
        report.failure_message = str(exc)
        _log.error("HARD FAIL: %s", exc)
    except Exception as exc:
        report.success = False
        report.failure_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        _log.exception("scenario failed")
    finally:
        report.duration_seconds_actual = timer.elapsed()
        report.finished_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
        for p in (peer_a, peer_b):
            try:
                p.conn.close()
            except Exception:
                pass
    return report


def _exchange(
    sender,
    recipient,
    exchange_dir: Path,
    report: ScenarioReport,
    rng: random.Random,
) -> None:
    tag = f"{sender.label}_to_{recipient.label}_{rng.randint(1, 10**9)}"
    path, result = export_to_file(sender, exchange_dir=exchange_dir, tag=tag)
    if sender.label == "A":
        report.exports_a_to_b += 1
    else:
        report.exports_b_to_a += 1
    direction = f"{sender.label}->{recipient.label}"
    outcome = import_from_file(recipient, path, direction_label=direction)
    if outcome.disposition == "ready_for_apply":
        if sender.label == "A":
            report.imports_a_to_b_ok += 1
        else:
            report.imports_b_to_a_ok += 1
    _log.info(
        "exchange %s disposition=%s package=%s",
        direction,
        outcome.disposition,
        outcome.package_id,
    )


def _corrupt_once(sender, recipient, exchange_dir: Path, report: ScenarioReport) -> None:
    """Corrupt a *copy* of a fresh export; then apply the good original to keep chains synced."""
    path, _result = export_to_file(
        sender, exchange_dir=exchange_dir, tag=f"corrupt_src_{sender.label}"
    )
    if sender.label == "A":
        report.exports_a_to_b += 1
    else:
        report.exports_b_to_a += 1

    raw = bytearray(path.read_bytes())
    if len(raw) < 16:
        raise RuntimeError("package too small to corrupt")
    mid = len(raw) // 2
    for i in range(mid, min(mid + 8, len(raw))):
        raw[i] ^= 0xFF
    corrupt_path = exchange_dir / f"CORRUPT_{path.name}"
    corrupt_path.write_bytes(raw)

    before = recipient.capture_transport_snapshot()
    business_before = recipient.conn.execute(
        "SELECT COUNT(*) FROM employees"
    ).fetchone()[0]
    assert recipient.inbound is not None
    try:
        recipient.inbound.ingest_from_path(corrupt_path)
        raise AssertionError("corrupted package was accepted — expected crypto failure")
    except AssertionError:
        raise
    except Exception as exc:
        _log.info(
            "corrupted package rejected as expected: %s: %s",
            type(exc).__name__,
            exc,
        )
        report.notes.append(
            f"corrupt reject: {type(exc).__name__}: {exc} (no product rejection audit row;"
            " assert unchanged snapshots)"
        )
    assert_unchanged_transport_and_business(recipient, before)
    business_after = recipient.conn.execute(
        "SELECT COUNT(*) FROM employees"
    ).fetchone()[0]
    if business_after != business_before:
        raise AssertionError("business employee count changed after corrupt import")
    report.corrupted_package_rejections += 1

    # Apply the untouched original so sender/recipient sequences stay aligned.
    direction = f"{sender.label}->{recipient.label}"
    outcome = import_from_file(recipient, path, direction_label=direction)
    if outcome.disposition == "ready_for_apply":
        if sender.label == "A":
            report.imports_a_to_b_ok += 1
        else:
            report.imports_b_to_a_ok += 1
    _log.info("post-corrupt good import disposition=%s", outcome.disposition)


def _restore_and_verify(peer, expected_snap: dict, report: ScenarioReport) -> None:
    assert peer.backup is not None and peer.backup_path is not None
    _log.info("%s restoring from %s", peer.label, peer.backup_path)
    new_conn = peer.backup.restore_backup(peer.backup_path)
    peer.reconnect_after_restore(new_conn)
    actual = peer.business_fingerprint()
    if actual != expected_snap:
        # Transport WK/package counts must match post-bootstrap; detail the diff.
        raise AssertionError(
            f"{peer.label}: restore did not return post-bootstrap state\n"
            f"expected_transport={expected_snap.get('transport')}\n"
            f"actual_transport={actual.get('transport')}\n"
            f"employees_expected={len(expected_snap.get('employees', []))}"
            f" actual={len(actual.get('employees', []))}"
        )
    report.notes.append(f"{peer.label} restore matches post-bootstrap snapshot")
