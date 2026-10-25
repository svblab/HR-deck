"""E0-01: карточки docs/work (README §10). Временный каталог, не дерево репозитория."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("work_status", ROOT / "scripts" / "work_status.py")
assert _SPEC is not None and _SPEC.loader is not None
work_status = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(work_status)


def _card(epic: str, name: str, **fields: str) -> str:
    data = {
        "id": name.removesuffix(".md"), "epic": epic, "title": "t", "status": "ready",
        "depends_on": "[]", "requires_adr": "none", "spec": "docs/work/README.md §10",
        "branch": "epic/E0-01-work-status-script", "size_budget": "300", "report": "",
        "allowed_paths": "[scripts/work_status.py]", "forbidden_paths": "[docs/TZ-v2.md]",
    }
    data.update(fields)
    rows = ["---", *[f"{key}: {value}" for key, value in data.items()], "---", ""]
    return "\n".join(rows)


def _write(root: Path, epic: str, name: str, text: str) -> None:
    path = root / "docs" / "work" / epic / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(root: Path, argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = work_status.main(argv, root=root)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_parse_list() -> None:
    meta = work_status.parse_front_matter(
        _card(
            "E0",
            "E0-01.md",
            depends_on="[E0-02, E0-03]",
            allowed_paths="[scripts/work_status.py, tests/unit/test_work_status.py]",
            forbidden_paths="[]",
        )
    )
    assert meta["depends_on"] == ["E0-02", "E0-03"]
    paths = ["scripts/work_status.py", "tests/unit/test_work_status.py"]
    assert meta["allowed_paths"] == paths
    assert meta["forbidden_paths"] == []


def test_parse_comment() -> None:
    text = "\n".join(
        [
            "---",
            "status: ready            # draft | ready | blocked | done",
            "title: keep#hash",
            "depends_on: [E0-02]  # ID карточек",
            "---",
            "",
        ]
    )
    meta = work_status.parse_front_matter(text)
    assert meta["status"] == "ready"
    assert meta["title"] == "keep#hash"
    assert meta["depends_on"] == ["E0-02"]


def test_dependency(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing"
    _write(missing, "E0", "E0-01.md", _card("E0", "E0-01.md", depends_on="[E0-99]"))
    code, _out, err = _run(missing, [], capsys)
    assert code == 1 and "несуществующий ID E0-99" in err

    waiting = tmp_path / "waiting"
    _write(waiting, "E0", "E0-02.md", _card("E0", "E0-02.md", status="draft"))
    _write(waiting, "E0", "E0-01.md", _card("E0", "E0-01.md", depends_on="[E0-02]"))
    code, out, err = _run(waiting, [], capsys)
    assert code == 0 and err == "" and "E0-02" in out and "нет" in out
    code, ready, err = _run(waiting, ["--ready"], capsys)
    assert code == 0 and err == "" and ready == ""

    done = tmp_path / "done"
    report = "docs/work/E0/reports/E0-02.md"
    _write(done, "E0", "E0-02.md", _card("E0", "E0-02.md", status="done", report=report))
    _write(done, "E0", "E0-01.md", _card("E0", "E0-01.md", depends_on="[E0-02]"))
    code, out, err = _run(done, [], capsys)
    assert code == 0 and err == "" and "да" in out
    code, ready, err = _run(done, ["--ready"], capsys)
    assert code == 0 and ready.strip() == "E0-01"


def test_consistency_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bare = tmp_path / "bare"
    _write(bare, "E0", "E0-01.md", _card("E0", "E0-01.md", status="done", report=""))
    code, _out, err = _run(bare, [], capsys)
    assert code == 1 and "status done без заполненного report" in err

    bad = tmp_path / "bad"
    _write(bad, "E0", "E0-01.md", _card("E0", "E0-01.md", status="published"))
    code, _out, err = _run(bad, [], capsys)
    assert code == 1 and "status не из draft, ready, blocked, done: published" in err

    copied = tmp_path / "copied"
    _write(copied, "E0", "E0-01.md", _card("E0", "E0-01.md"))
    _write(copied, "E0", "E0-02.md", _card("E0", "E0-02.md", id="E0-01"))
    code, _out, err = _run(copied, [], capsys)
    assert code == 1 and "дубликат id E0-01" in err

    (tmp_path / "docs" / "work").mkdir(parents=True)
    code, out, err = _run(tmp_path, [], capsys)
    assert code == 0 and err == "" and out.strip() == "карточек нет"
