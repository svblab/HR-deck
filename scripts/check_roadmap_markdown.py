#!/usr/bin/env python3
"""Sanity checks for docs/ROADMAP.md (tables, links, whitespace)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "ROADMAP.md"


def main() -> int:
    if not ROADMAP.is_file():
        print(f"FAIL: missing {ROADMAP}")
        return 1

    text = ROADMAP.read_text(encoding="utf-8")
    errors: list[str] = []

    for i, line in enumerate(text.splitlines(), 1):
        if line.rstrip() != line:
            errors.append(f"trailing whitespace line {i}")
        if line.startswith("|") and line.strip() and not line.endswith("|"):
            errors.append(f"table row missing trailing pipe line {i}")

    for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "#")):
            continue
        rel = (ROADMAP.parent / target).resolve()
        if not rel.exists():
            errors.append(f"missing relative link target: {target}")

    for i, line in enumerate(text.splitlines(), 1):
        if not line.startswith("| EPIC-"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) != 4:
            errors.append(f"EPIC table row line {i}: {len(cols)} columns, expected 4")

    if errors:
        print("ROADMAP markdown sanity: FAIL")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("ROADMAP markdown sanity: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
