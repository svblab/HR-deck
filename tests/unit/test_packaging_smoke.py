"""Smoke: файлы упаковки .deb и discover миграций из wheel (EPIC-015)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _venv_bin(venv: Path, name: str) -> Path:
    scripts = "Scripts" if sys.platform == "win32" else "bin"
    return venv / scripts / name


def test_packaging_scaffold_files_exist() -> None:
    required = [
        "packaging/README.md",
        "packaging/debian/control",
        "packaging/debian/rules",
        "packaging/debian/changelog",
        "packaging/debian/postinst",
        "packaging/debian/build-venv.sh",
        "packaging/debian/install-venv.sh",
        "packaging/debian/personnel-availability-launcher",
        "packaging/personnel-availability.desktop",
        "scripts/build-deb.sh",
        "scripts/verify-deb-smoke.sh",
        "scripts/verify-deb-install.sh",
    ]
    for rel in required:
        assert (ROOT / rel).is_file(), rel


def test_ci_offline_smoke_uses_network_none() -> None:
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "--network none" in text
    assert "verify-deb-smoke.sh" in text


def test_desktop_entry_has_exec_and_name() -> None:
    text = (ROOT / "packaging/personnel-availability.desktop").read_text(encoding="utf-8")
    assert "Exec=personnel-availability" in text
    assert "Name=Журнал доступности персонала" in text


def test_control_uses_vendored_runtime_not_pyside6_apt() -> None:
    text = (ROOT / "packaging/debian/control").read_text(encoding="utf-8")
    assert "Package: personnel-availability" in text
    assert "python3-pyside6" not in text
    assert "libegl1" in text
    assert "Architecture: amd64" in text


def test_postinst_does_not_touch_user_data() -> None:
    text = (ROOT / "packaging/debian/postinst").read_text(encoding="utf-8")
    assert ".local/share" in text


def test_migrations_discoverable_from_built_wheel(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = _venv_bin(venv, "python")
    subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip", "build", "-q"], check=True)
    subprocess.run(
        [str(py), "-m", "build", "--wheel", "-o", str(tmp_path / "dist")],
        check=True,
        cwd=ROOT,
    )
    wheels = list((tmp_path / "dist").glob("*.whl"))
    assert wheels
    subprocess.run([str(py), "-m", "pip", "install", "-q", str(wheels[0])], check=True)
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
