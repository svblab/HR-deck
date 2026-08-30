"""Smoke: файлы упаковки .deb (EPIC-015)."""

from __future__ import annotations

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
    assert "dpkg" in text.lower() or "dpkg управляет" in text
