"""Qt-free package delivery helpers (Issue #130)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from ui.package_delivery import (
    TrackedTemp,
    cleanup_tracked_temps,
    deliver_package,
    normalize_hrpkg_path,
    preflight_writable,
    unlink_quiet,
)


def test_normalize_hrpkg_path_cases() -> None:
    assert normalize_hrpkg_path(Path("out")).name == "out.hrpkg"
    assert normalize_hrpkg_path(Path("отчёт v1.2")).name == "отчёт v1.2.hrpkg"
    assert normalize_hrpkg_path(Path("out.txt")).name == "out.txt.hrpkg"
    assert normalize_hrpkg_path(Path("out.hrpkg")).name == "out.hrpkg"
    assert normalize_hrpkg_path(Path("out.HRPKG")).name == "out.HRPKG"
    assert normalize_hrpkg_path(Path("x.hrpkg.hrpkg")).name == "x.hrpkg.hrpkg"


def test_preflight_writable_uses_exclusive_unique_temp(tmp_path: Path) -> None:
    save_path = tmp_path / "out.hrpkg"
    leftover = tmp_path / "out.hrpkg.partial"
    leftover.write_bytes(b"DO-NOT-TOUCH")
    probe = preflight_writable(save_path)
    assert probe.name.startswith("out.hrpkg.")
    assert probe.name.endswith(".partial")
    assert probe != leftover
    assert leftover.read_bytes() == b"DO-NOT-TOUCH"
    unlink_quiet(probe)


def test_deliver_package_keeps_complete_temp_on_replace_failure(tmp_path: Path) -> None:
    save_path = tmp_path / "out.hrpkg"
    with patch(
        "ui.package_delivery.os.replace",
        side_effect=OSError("busy"),
    ):
        outcome = deliver_package(b"payload-bytes", save_path)
    assert outcome.final_path is None
    assert outcome.complete_temp is not None
    assert outcome.complete_temp.is_file()
    assert outcome.complete_temp.read_bytes() == b"payload-bytes"
    assert not save_path.exists()
    outcome2 = deliver_package(
        b"ignored",
        save_path,
        reuse_complete_temp=outcome.complete_temp,
    )
    assert outcome2.final_path == save_path
    assert save_path.read_bytes() == b"payload-bytes"
    assert not outcome.complete_temp.exists()


def test_deliver_does_not_replace_old_temp_into_new_path(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    old_temp = dir_a / "out.hrpkg.deadbeef.partial"
    old_temp.write_bytes(b"OLD")
    new_path = dir_b / "out.hrpkg"
    replace_srcs: list[Path] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        replace_srcs.append(Path(src))
        return real_replace(src, dst)

    with patch("ui.package_delivery.os.replace", side_effect=spy_replace):
        outcome = deliver_package(b"NEW", new_path, reuse_complete_temp=None)
    assert outcome.final_path == new_path
    assert new_path.read_bytes() == b"NEW"
    assert old_temp.read_bytes() == b"OLD"
    assert old_temp not in replace_srcs
    assert all(src.parent == dir_b for src in replace_srcs)


def test_cleanup_tracked_temps_deletes_only_tracked_after_success(tmp_path: Path) -> None:
    keep = tmp_path / "keep.hrpkg.partial"
    keep.write_bytes(b"KEEP")
    t1 = tmp_path / "out.hrpkg.aaaaaaaa.partial"
    t2 = tmp_path / "out.hrpkg.bbbbbbbb.partial"
    t1.write_bytes(b"1")
    t2.write_bytes(b"2")
    tracked = [
        TrackedTemp(path=t1, for_save_path=tmp_path / "out.hrpkg"),
        TrackedTemp(path=t2, for_save_path=tmp_path / "other.hrpkg"),
    ]
    cleanup_tracked_temps(tracked)
    assert not t1.exists()
    assert not t2.exists()
    assert keep.exists() and keep.read_bytes() == b"KEEP"
