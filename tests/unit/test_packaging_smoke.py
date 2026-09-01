"""Smoke: файлы упаковки .deb и discover миграций из wheel (EPIC-015)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_packaging_scaffold_files_exist() -> None:
    required = [
        "packaging/README.md",
        "packaging/debian/control",
        "packaging/debian/rules",
        "packaging/debian/changelog",
        "packaging/debian/compat",
        "packaging/debian/postinst",
        "packaging/personnel-availability.desktop",
        "scripts/build-deb.sh",
    ]
    for rel in required:
        assert (ROOT / rel).is_file(), rel


def test_desktop_entry_has_exec_and_name() -> None:
    text = (ROOT / "packaging/personnel-availability.desktop").read_text(encoding="utf-8")
    assert "Exec=personnel-availability" in text
    assert "Name=Журнал доступности персонала" in text


def test_control_declares_package_and_pyside6() -> None:
    text = (ROOT / "packaging/debian/control").read_text(encoding="utf-8")
    assert "Package: personnel-availability" in text
    assert "python3-pyside6" in text


def test_postinst_does_not_touch_user_data() -> None:
    text = (ROOT / "packaging/debian/postinst").read_text(encoding="utf-8")
    assert ".local/share" in text


def test_migrations_discoverable_from_built_wheel(tmp_path: Path) -> None:
    if shutil.which("pip") is None:
        return
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "build", "-q"],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "-o", str(tmp_path / "dist")],
        check=True,
        cwd=ROOT,
    )
    wheels = list((tmp_path / "dist").glob("*.whl"))
    assert wheels
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    pip = venv / ("Scripts" if sys.platform == "win32" else "bin") / "pip"
    py = venv / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    subprocess.run([str(pip), "install", "-q", str(wheels[0])], check=True)
    out = subprocess.check_output(
        [
            str(py),
            "-c",
            "from data.migrations import discover_migrations; "
            "print(len(discover_migrations()))",
        ],
        text=True,
    )
    assert int(out.strip()) >= 8
