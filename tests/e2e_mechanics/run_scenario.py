"""CLI entry-point for the dual-peer E2E mechanics scenario."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from tests.e2e_mechanics.report import ScenarioReport
from tests.e2e_mechanics.scenario import run_scenario

_DEFAULT_SEED = 20260927
_DEFAULT_DURATION = 24 * 60  # ~24 minutes
_MAX_DURATION = 60 * 60


def _configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    # Windows consoles (cp1251) may not encode all Unicode log messages.
    if hasattr(sh.stream, "reconfigure"):
        try:
            sh.stream.reconfigure(errors="replace")
        except OSError:
            pass
    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(sh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Headless dual-peer E2E: transport exchange, backup/restore, "
            "one corrupted package, EPIC-018 conversion, EPIC-007 clarification."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/e2e-data") if Path("/e2e-data").is_dir() else Path("._e2e_mechanics"),
        help="Working root for peer-a / peer-b / exchange volumes",
    )
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=_DEFAULT_DURATION,
        help=f"Wall-clock timed loop (default {_DEFAULT_DURATION}, max {_MAX_DURATION})",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="Directory for report JSON/MD (default: <root>/report)",
    )
    args = parser.parse_args(argv)
    if args.duration_seconds > _MAX_DURATION:
        parser.error(f"--duration-seconds exceeds hard cap {_MAX_DURATION}")

    root: Path = args.root
    root.mkdir(parents=True, exist_ok=True)
    report_dir: Path = args.report_dir or (root / "report")
    report_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(report_dir / "scenario.log")

    logging.getLogger("e2e_mechanics").info(
        "starting seed=%s duration=%ss root=%s",
        args.seed,
        args.duration_seconds,
        root,
    )
    report: ScenarioReport = run_scenario(
        root=root,
        seed=args.seed,
        duration_seconds=args.duration_seconds,
    )
    out = report_dir / "report.json"
    report.write(out)
    logging.getLogger("e2e_mechanics").info(
        "finished success=%s report=%s", report.success, out
    )
    print(f"REPORT_JSON={out}")
    print(f"REPORT_MD={out.with_suffix('.md')}")
    print(f"SUCCESS={report.success}")
    return 0 if report.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
