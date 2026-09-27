"""Domain mutations for the timed loop (employees, statuses, conversion)."""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

from domain.employee import EmployeeCreateInput, EmployeeUpdateInput, normalize_name_for_match
from services.employee_files import write_xlsx
from tests.e2e_mechanics.peer import Peer
from tests.e2e_mechanics.report import ScenarioReport

_log = logging.getLogger("e2e_mechanics.actions")

# Prefer statuses with optional/required end_date that we always supply.
_STATUS_OFFICE = 1
_STATUS_TRIP = 3
_STATUS_SICK = 4


def create_unique_employee(peer: Peer, rng: random.Random, report: ScenarioReport) -> int:
    assert peer.org is not None and peer.employees is not None
    seq = report.employees_created + 1
    # Globally unique FIO across peers → avoids AMBIGUOUS/LOW on later sync.
    full_name = f"E2E {peer.label} Worker {seq:05d} R{rng.randint(1000, 9999)}"
    emp_id = peer.employees.create_employee(
        EmployeeCreateInput(
            full_name=full_name,
            position_id=peer.org.position_id,
            branch_id=peer.org.branch_id,
            department_id=peer.org.department_id,
            division_id=peer.org.division_id,
            employment_type_id=peer.org.employment_type_id,
            note=f"synthetic:{peer.label}:{seq}",
        )
    )
    report.employees_created += 1
    _log.info("%s created employee id=%s name=%r", peer.label, emp_id, full_name)
    return emp_id


def edit_random_employee(peer: Peer, rng: random.Random) -> None:
    assert peer.employees is not None and peer.org is not None
    cards = peer.employees.list_employees(active_only=True)
    # Only edit employees originally created on this peer (name prefix).
    local = [c for c in cards if c.full_name.startswith(f"E2E {peer.label} ")]
    if not local:
        return
    card = rng.choice(local)
    note = f"edited@{peer.clock()}#{rng.randint(1, 1_000_000)}"
    peer.employees.update_employee(
        card.id,
        EmployeeUpdateInput(
            full_name=card.full_name,
            position_id=card.position_id,
            branch_id=card.branch_id,
            department_id=card.department_id,
            division_id=card.division_id,
            employment_type_id=card.employment_type_id,
            note=note,
        ),
    )
    _log.info("%s edited employee id=%s", peer.label, card.id)


def assign_status_variants(peer: Peer, rng: random.Random, report: ScenarioReport) -> None:
    """Assign past / current / future statuses on a clean employee timeline."""
    assert peer.statuses is not None and peer.employees is not None
    # Prefer a fresh card so open-ended / future periods never collide.
    emp_id = create_unique_employee(peer, rng, report)
    today = peer.clock.date
    kind = rng.choice(["current", "past_expired", "future", "past_then_current"])
    if kind == "current":
        peer.statuses.assign_status(
            emp_id,
            status_id=_STATUS_OFFICE,
            start_date=today,
            end_date=None,
            confirmed=True,
        )
    elif kind == "past_expired":
        peer.statuses.assign_status(
            emp_id,
            status_id=_STATUS_TRIP,
            start_date=_shift_date(today, -10),
            end_date=_shift_date(today, -1),
            confirmed=True,
        )
    elif kind == "future":
        peer.statuses.assign_status(
            emp_id,
            status_id=_STATUS_SICK,
            start_date=_shift_date(today, 3),
            end_date=_shift_date(today, 7),
            confirmed=True,
        )
    else:
        peer.statuses.assign_status(
            emp_id,
            status_id=_STATUS_TRIP,
            start_date=_shift_date(today, -5),
            end_date=_shift_date(today, -2),
            confirmed=True,
        )
        peer.statuses.assign_status(
            emp_id,
            status_id=_STATUS_OFFICE,
            start_date=today,
            end_date=None,
            confirmed=True,
        )
    report.status_assignments += 1
    _log.info("%s status kind=%s employee=%s", peer.label, kind, emp_id)


def raise_and_clear_clarification(
    peer: Peer, rng: random.Random, report: ScenarioReport
) -> None:
    assert peer.clarify is not None and peer.statuses is not None
    assert peer.employees is not None
    before = peer.clarify.count_needing_clarification()
    emp_id = create_unique_employee(peer, rng, report)
    today = peer.clock.date
    peer.statuses.assign_status(
        emp_id,
        status_id=_STATUS_TRIP,
        start_date=_shift_date(today, -7),
        end_date=_shift_date(today, -1),
        confirmed=True,
    )
    mid = peer.clarify.count_needing_clarification()
    if mid > before:
        report.clarification_raised += mid - before
    assert peer.clarify.employee_needs_clarification(emp_id)
    peer.statuses.assign_status(
        emp_id,
        status_id=_STATUS_OFFICE,
        start_date=today,
        end_date=None,
        confirmed=True,
    )
    after = peer.clarify.count_needing_clarification()
    if after < mid:
        report.clarification_cleared += mid - after
    assert not peer.clarify.employee_needs_clarification(emp_id)
    _log.info(
        "%s clarification before=%s mid=%s after=%s",
        peer.label,
        before,
        mid,
        after,
    )


def run_conversion_batch(
    peer: Peer,
    rng: random.Random,
    report: ScenarioReport,
    *,
    work_dir: Path,
    force_fio_collision: bool,
) -> None:
    """EPIC-018: ingest incomplete rows; save new / skip collisions (no auto-link)."""
    assert peer.org is not None
    assert peer.ingest is not None and peer.conversion is not None
    assert peer.employees is not None and peer.sessions is not None

    collision_name: str | None = None
    if force_fio_collision:
        cards = [
            c
            for c in peer.employees.list_employees(active_only=True)
            if c.full_name.startswith(f"E2E {peer.label} ")
        ]
        if cards:
            collision_name = cards[0].full_name

    rows: list[list[str]] = []
    n_new = rng.randint(2, 4)
    for i in range(n_new):
        rows.append(
            [
                f"Conv {peer.label} {report.conversion_sessions+1:03d}-{i:02d} "
                f"U{rng.randint(10000, 99999)}",
                "",
                "",
            ]
        )
    if collision_name:
        rows.append([collision_name, "ignored-title", ""])

    path = work_dir / f"conv_{peer.label}_{report.conversion_sessions + 1}.xlsx"
    write_xlsx(path, ["ФИО", "Должность", "Филиал"], rows)
    result = peer.ingest.ingest_file(path)
    report.conversion_sessions += 1
    staged = peer.sessions.list_rows(result.session_id)
    _log.info(
        "%s conversion session=%s staged=%s resumed=%s",
        peer.label,
        result.session_id,
        len(staged),
        result.resumed,
    )

    for row in list(staged):
        values = json.loads(row.values_json)
        full_name = str(values.get("full_name", "")).strip()
        hits = [
            h
            for h in peer.employees.search_by_name(full_name)
            if normalize_name_for_match(h.full_name) == normalize_name_for_match(full_name)
        ]
        if hits:
            report.conversion_fio_collisions_observed += 1
            peer.conversion.skip_row(
                session_id=result.session_id,
                row_id=row.id,
                last_accessed_at=peer.clock(),
            )
            report.conversion_rows_skipped += 1
            _log.info(
                "%s skip FIO collision name=%r matches=%s",
                peer.label,
                full_name,
                [h.id for h in hits],
            )
            continue
        peer.conversion.save_row(
            session_id=result.session_id,
            row_id=row.id,
            data=EmployeeCreateInput(
                full_name=full_name,
                position_id=peer.org.position_id,
                branch_id=peer.org.branch_id,
                department_id=peer.org.department_id,
                division_id=peer.org.division_id,
                employment_type_id=peer.org.employment_type_id,
                note="conversion",
            ),
            last_accessed_at=peer.clock(),
        )
        report.conversion_rows_saved += 1
        report.employees_created += 1


def _shift_date(iso_date: str, days: int) -> str:
    from datetime import date, timedelta

    d = date.fromisoformat(iso_date)
    return (d + timedelta(days=days)).isoformat()
