"""Состояние карточек docs/work (E0-01). Только стандартная библиотека."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REQUIRED = (
    "id", "epic", "title", "status", "depends_on", "requires_adr", "spec",
    "branch", "size_budget", "allowed_paths", "forbidden_paths", "report",
)
STATUSES = frozenset({"draft", "ready", "blocked", "done"})
SKIP_DIRS = frozenset({"_templates", "reports"})
HEADERS = ("ID", "EPIC", "status", "ждёт", "можно брать")
Meta = dict[str, str | list[str]]
Card = tuple[Path, Meta]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def parse_front_matter(text: str) -> Meta:
    lines = text.splitlines()
    fences = [index for index, line in enumerate(lines) if line.strip() == "---"]
    data: Meta = {}
    if len(fences) < 2:
        return data
    for line in lines[fences[0] + 1 : fences[1]]:
        key, sep, raw = line.partition(":")
        if not sep or not key.strip():
            continue
        value = raw.strip().split(" #", 1)[0].rstrip()
        data[key.strip()] = _parse_value(value)
    return data


def _parse_value(value: str) -> str | list[str]:
    if len(value) >= 2 and value[0] == "[" and value[-1] == "]":
        inner = value[1:-1].strip()
        return [part.strip() for part in inner.split(",")] if inner else []
    return value


def load_cards(root: Path) -> list[Card]:
    work = root / "docs" / "work"
    if not work.is_dir():
        return []
    cards: list[Card] = []
    epics = [path for path in work.iterdir() if path.is_dir() and path.name not in SKIP_DIRS]
    for epic in sorted(epics, key=lambda path: path.name):
        pages = [path for path in epic.glob("*.md") if path.name != "README.md"]
        for path in sorted(pages, key=lambda path: path.name):
            cards.append((path, parse_front_matter(path.read_text(encoding="utf-8"))))
    return cards


def validate(cards: list[Card], root: Path) -> list[str]:
    errors: list[str] = []
    seen: dict[str, list[str]] = {}
    known: set[str] = set()
    for path, meta in cards:
        card_id = meta.get("id")
        if isinstance(card_id, str) and card_id:
            known.add(card_id)
            seen.setdefault(card_id, []).append(path.relative_to(root).as_posix())
    for path, meta in cards:
        label = path.relative_to(root).as_posix()
        for key in REQUIRED:
            if key not in meta:
                errors.append(f"{label}: нет обязательного ключа {key}")
        status = meta.get("status")
        if "status" in meta and status not in STATUSES:
            errors.append(f"{label}: status не из draft, ready, blocked, done: {status}")
        card_id = meta.get("id")
        if isinstance(card_id, str) and card_id and card_id != path.stem:
            errors.append(f"{label}: id {card_id} не совпадает с именем файла {path.stem}")
        report = meta.get("report")
        if status == "done" and not (isinstance(report, str) and report.strip()):
            errors.append(f"{label}: status done без заполненного report")
        deps = meta.get("depends_on")
        if "depends_on" in meta and not isinstance(deps, list):
            errors.append(f"{label}: depends_on не список")
        elif isinstance(deps, list):
            for dep in deps:
                if dep not in known:
                    errors.append(f"{label}: depends_on ссылается на несуществующий ID {dep}")
    for card_id in sorted(seen):
        if len(seen[card_id]) > 1:
            errors.append(f"дубликат id {card_id}: {', '.join(seen[card_id])}")
    return errors


def _index(cards: list[Card]) -> dict[str, Meta]:
    indexed: dict[str, Meta] = {}
    for _path, meta in cards:
        card_id = meta.get("id")
        if isinstance(card_id, str) and card_id:
            indexed[card_id] = meta
    return indexed


def _waiting(meta: Meta, indexed: dict[str, Meta]) -> list[str]:
    deps = meta.get("depends_on")
    if not isinstance(deps, list):
        return []
    return [dep for dep in deps if indexed.get(dep, {}).get("status") != "done"]


def _can_take(meta: Meta, indexed: dict[str, Meta]) -> bool:
    deps = meta.get("depends_on")
    if meta.get("status") != "ready" or not isinstance(deps, list):
        return False
    return all(indexed.get(dep, {}).get("status") == "done" for dep in deps)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def render_table(cards: list[Card]) -> str:
    indexed = _index(cards)

    def sort_key(item: Card) -> tuple[str, str]:
        path, meta = item
        return (_text(meta.get("id")), path.as_posix())

    body: list[tuple[str, str, str, str, str]] = []
    for _path, meta in sorted(cards, key=sort_key):
        waiting = _waiting(meta, indexed)
        body.append(
            (
                _text(meta.get("id")),
                _text(meta.get("epic")),
                _text(meta.get("status")),
                ", ".join(waiting) if waiting else "-",
                "да" if _can_take(meta, indexed) else "нет",
            )
        )
    widths = [len(cell) for cell in HEADERS]
    for row in body:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def fmt(row: tuple[str, ...]) -> str:
        padded = [cell.ljust(widths[index]) for index, cell in enumerate(row)]
        return "  ".join(padded).rstrip()

    lines = [fmt(HEADERS), "  ".join("-" * width for width in widths)]
    lines.extend(fmt(row) for row in body)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Состояние карточек docs/work")
    parser.add_argument("--ready", action="store_true", help="ID карточек, которые можно брать")
    args = parser.parse_args(argv)
    base = repo_root() if root is None else root
    cards = load_cards(base)
    if not cards:
        print("карточек нет")
        return 0
    errors = validate(cards, base)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    indexed = _index(cards)
    if args.ready:
        ready = [
            _text(meta.get("id"))
            for _path, meta in cards
            if _text(meta.get("id")) and _can_take(meta, indexed)
        ]
        if ready:
            print("\n".join(sorted(ready)))
        return 0
    sys.stdout.write(render_table(cards))
    return 0


if __name__ == "__main__":
    sys.exit(main())
