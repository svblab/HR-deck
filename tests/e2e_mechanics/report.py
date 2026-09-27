"""Scenario metrics and structured report writer."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ScenarioReport:
    seed: int
    duration_seconds_target: int
    duration_seconds_actual: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    success: bool = False
    failure_message: str | None = None
    exports_a_to_b: int = 0
    exports_b_to_a: int = 0
    imports_a_to_b_ok: int = 0
    imports_b_to_a_ok: int = 0
    corrupted_package_rejections: int = 0
    conversion_sessions: int = 0
    conversion_rows_saved: int = 0
    conversion_rows_skipped: int = 0
    conversion_fio_collisions_observed: int = 0
    clarification_raised: int = 0
    clarification_cleared: int = 0
    employees_created: int = 0
    status_assignments: int = 0
    restore_verified: bool = False
    notes: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        md = path.with_suffix(".md")
        lines = [
            "# E2E Mechanics Report",
            "",
            f"- **success:** {self.success}",
            f"- **seed:** `{self.seed}`",
            f"- **duration:** {self.duration_seconds_actual:.1f}s"
            f" (target {self.duration_seconds_target}s)",
            f"- **started:** {self.started_at}",
            f"- **finished:** {self.finished_at}",
            "",
            "## Transport",
            f"- exports A→B: {self.exports_a_to_b}",
            f"- exports B→A: {self.exports_b_to_a}",
            f"- imports A→B ok: {self.imports_a_to_b_ok}",
            f"- imports B→A ok: {self.imports_b_to_a_ok}",
            f"- corrupted-package rejections: {self.corrupted_package_rejections}",
            "",
            "## Conversion (EPIC-018)",
            f"- sessions: {self.conversion_sessions}",
            f"- rows saved: {self.conversion_rows_saved}",
            f"- rows skipped: {self.conversion_rows_skipped}",
            f"- FIO collisions observed (no auto-link): "
            f"{self.conversion_fio_collisions_observed}",
            "",
            "## Requires attention (EPIC-007)",
            f"- raised: {self.clarification_raised}",
            f"- cleared: {self.clarification_cleared}",
            "",
            "## Other",
            f"- employees created: {self.employees_created}",
            f"- status assignments: {self.status_assignments}",
            f"- restore verified: {self.restore_verified}",
        ]
        if self.failure_message:
            lines.extend(["", "## Failure", "```", self.failure_message, "```"])
        if self.notes:
            lines.extend(["", "## Notes", *[f"- {n}" for n in self.notes]])
        lines.append("")
        md.write_text("\n".join(lines), encoding="utf-8")


class WallTimer:
    def __init__(self) -> None:
        self.t0 = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self.t0
