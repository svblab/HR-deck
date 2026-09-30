"""UI: transport export panel (Issue #130)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox

from domain.transport import DirectionStatus
from services.bootstrap import BootstrapService
from services.employees import EmployeeService
from services.transport_export import TransportExportResult
from services.transport_operator import OutboundExportTarget, PersonnelTransportExportResult
from ui.package_delivery import DeliveryResult, TrackedTemp
from ui.transport_export_dialog import TransportExportPanel, _default_export_filename

_T0 = "2026-09-29T15:00:00Z"


def _open(tmp_path: Path):
    db = tmp_path / "app.db"
    conn, session, _ = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    return conn, session, employees, db


def _panel_ready(qtbot, tmp_path: Path, *, preview_tables: dict | None = None):
    conn, session, _employees, _db = _open(tmp_path)
    panel = TransportExportPanel(conn, session)
    qtbot.addWidget(panel)
    panel._targets = [
        OutboundExportTarget(
            direction_id=1,
            peer_label="Peer",
            direction_status=DirectionStatus.ACTIVE,
            generation=0,
            accepted_sequence=0,
        )
    ]
    panel._direction_combo.clear()
    panel._direction_combo.addItem("Peer", 1)
    panel._preview_tables = preview_tables if preview_tables is not None else {"branches": [{}]}
    panel._stack.setCurrentIndex(1)
    return conn, panel


def _personnel_result(*, wire: bytes = b"wire-bytes") -> PersonnelTransportExportResult:
    export_result = TransportExportResult(
        package=MagicMock(),
        wire_bytes=wire,
        package_id="pkg-1",
        generation=0,
        sequence=1,
        direction_id=1,
    )
    return PersonnelTransportExportResult(
        export=export_result,
        tables_exported=("branches",),
        payload_empty=False,
    )


def test_export_panel_shows_directions(qtbot, tmp_path: Path) -> None:
    conn, session, _employees, _db = _open(tmp_path)
    panel = TransportExportPanel(conn, session)
    qtbot.addWidget(panel)
    targets = [
        OutboundExportTarget(
            direction_id=7,
            peer_label="Peer",
            direction_status=DirectionStatus.ACTIVE,
            generation=0,
            accepted_sequence=0,
        )
    ]
    with patch.object(panel._operator, "list_outbound_export_targets", return_value=targets):
        panel._reload_targets()
    combo = panel.findChild(type(panel._direction_combo), "transportExportDirectionCombo")
    assert combo is not None
    assert combo.count() == 1
    conn.close()


def test_export_panel_runs_export_and_save(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"
    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(),
        ) as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(save_path), ""),
        ),
    ):
        panel._run_export()
    export_mock.assert_called_once_with(1)
    assert save_path.read_bytes() == b"wire-bytes"
    leftovers = list(tmp_path.glob("out.hrpkg.*.partial"))
    assert leftovers == []
    assert panel._stack.currentIndex() == 2
    conn.close()


def test_cancel_dialog_does_not_call_operator(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    with (
        patch.object(panel._operator, "export_personnel_package") as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=("", ""),
        ),
    ):
        panel._run_export()
    export_mock.assert_not_called()
    assert panel._stack.currentIndex() == 1
    conn.close()


def test_preflight_failure_does_not_call_operator(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"
    with (
        patch.object(panel._operator, "export_personnel_package") as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(save_path), ""),
        ),
        patch(
            "ui.transport_export_dialog.preflight_writable",
            side_effect=OSError("preflight denied"),
        ),
        patch("ui.transport_export_dialog.QMessageBox.warning") as warn,
    ):
        panel._run_export()
    export_mock.assert_not_called()
    warn.assert_called_once()
    assert "подготовить файл" in warn.call_args.args[2]
    assert not save_path.exists()
    conn.close()


def test_export_raises_removes_unique_temp_leaves_final_untouched(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"
    save_path.write_bytes(b"existing-final")
    probe = tmp_path / "out.hrpkg.aabbccdd.partial"

    def fake_preflight(_path: Path) -> Path:
        probe.write_bytes(b"")
        return probe

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            side_effect=RuntimeError("crypto boom"),
        ) as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(save_path), ""),
        ),
        patch(
            "ui.transport_export_dialog.preflight_writable",
            side_effect=fake_preflight,
        ),
        patch("ui.transport_export_dialog.QMessageBox.warning") as warn,
    ):
        panel._run_export()
    export_mock.assert_called_once_with(1)
    warn.assert_called_once()
    assert "crypto boom" in warn.call_args.args[2]
    assert not probe.exists()
    assert save_path.read_bytes() == b"existing-final"
    conn.close()


def test_preexisting_bare_partial_not_modified_by_new_export(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"
    leftover = tmp_path / "out.hrpkg.partial"
    leftover.write_bytes(b"COMPLETE-OLD-PACKAGE")
    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(wire=b"new-wire"),
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(save_path), ""),
        ),
    ):
        panel._run_export()
    assert leftover.read_bytes() == b"COMPLETE-OLD-PACKAGE"
    assert save_path.read_bytes() == b"new-wire"
    conn.close()


def test_write_fails_then_retry_succeeds_operator_once(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"
    calls = {"n": 0}

    def flaky_deliver(wire_bytes: bytes, path: Path, *, reuse_complete_temp=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return DeliveryResult(error=OSError("disk full"))
        path.write_bytes(wire_bytes)
        return DeliveryResult(final_path=path)

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(),
        ) as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(save_path), ""),
        ),
        patch("ui.transport_export_dialog.deliver_package", side_effect=flaky_deliver),
        patch.object(panel, "_ask_delivery_action", return_value="retry"),
    ):
        panel._run_export()
    export_mock.assert_called_once()
    assert calls["n"] == 2
    assert save_path.read_bytes() == b"wire-bytes"
    assert panel._stack.currentIndex() == 2
    conn.close()


def test_replace_fails_complete_temp_retry_replace_only(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"
    replace_calls = {"n": 0}
    real_replace = os.replace

    def flaky_replace(src, dst):
        replace_calls["n"] += 1
        if replace_calls["n"] == 1:
            raise OSError("target locked")
        return real_replace(src, dst)

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(wire=b"pkg-data"),
        ) as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(save_path), ""),
        ),
        patch("ui.package_delivery.os.replace", side_effect=flaky_replace),
        patch.object(panel, "_ask_delivery_action", return_value="retry"),
    ):
        panel._run_export()
    export_mock.assert_called_once()
    assert replace_calls["n"] == 2
    assert save_path.read_bytes() == b"pkg-data"
    assert list(tmp_path.glob("out.hrpkg.*.partial")) == []
    assert panel._stack.currentIndex() == 2
    conn.close()


def test_replace_fail_relocate_other_dir_rewrites_and_cleans_old_temp(
    qtbot, tmp_path: Path
) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    dir_a = tmp_path / "vol_a"
    dir_b = tmp_path / "vol_b"
    dir_a.mkdir()
    dir_b.mkdir()
    first = dir_a / "out.hrpkg"
    second = dir_b / "out.hrpkg"
    replace_pairs: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def tracking_replace(src, dst):
        src_p, dst_p = Path(src), Path(dst)
        replace_pairs.append((src_p, dst_p))
        if dst_p == first:
            raise OSError("locked on a")
        return real_replace(src, dst)

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(wire=b"cross-vol"),
        ) as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            side_effect=[(str(first), ""), (str(second), "")],
        ),
        patch("ui.package_delivery.os.replace", side_effect=tracking_replace),
        patch.object(panel, "_ask_delivery_action", return_value="relocate"),
    ):
        panel._run_export()
    export_mock.assert_called_once()
    assert second.read_bytes() == b"cross-vol"
    assert not first.exists()
    assert list(dir_a.glob("*.partial")) == []
    assert list(dir_b.glob("*.partial")) == []
    assert not any(src.parent == dir_a and dst == second for src, dst in replace_pairs)
    assert panel._stack.currentIndex() == 2
    conn.close()


def test_relocate_dialog_cancelled_returns_to_menu_no_extra_attempt(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"
    deliver_calls = {"n": 0}
    ask_calls = {"n": 0}

    def fail_deliver(wire_bytes: bytes, path: Path, *, reuse_complete_temp=None):
        deliver_calls["n"] += 1
        return DeliveryResult(error=OSError("fail"))

    def ask(*, error, save_path):
        ask_calls["n"] += 1
        if ask_calls["n"] == 1:
            return "relocate"
        return "abandon"

    dialog_returns = iter([(str(save_path), ""), ("", "")])

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(),
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            side_effect=lambda *a, **k: next(dialog_returns),
        ),
        patch("ui.transport_export_dialog.deliver_package", side_effect=fail_deliver),
        patch.object(panel, "_ask_delivery_action", side_effect=ask),
        patch.object(panel, "_confirm_abandon", return_value=True),
        patch.object(panel, "_show_abandon_final"),
    ):
        panel._run_export()
    assert deliver_calls["n"] == 1
    assert ask_calls["n"] == 2
    conn.close()


def test_abandon_confirmation_no_returns_to_menu_no_attempt(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"
    deliver_calls = {"n": 0}
    ask_calls = {"n": 0}
    confirm_answers = iter([False, True])

    def fail_deliver(wire_bytes: bytes, path: Path, *, reuse_complete_temp=None):
        deliver_calls["n"] += 1
        return DeliveryResult(error=OSError("fail"))

    def ask(*, error, save_path):
        ask_calls["n"] += 1
        return "abandon"

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(),
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(save_path), ""),
        ),
        patch("ui.transport_export_dialog.deliver_package", side_effect=fail_deliver),
        patch.object(panel, "_ask_delivery_action", side_effect=ask),
        patch.object(
            panel,
            "_confirm_abandon",
            side_effect=lambda tracked: next(confirm_answers),
        ),
        patch.object(panel, "_show_abandon_final") as final_msg,
    ):
        panel._run_export()
    assert deliver_calls["n"] == 1
    assert ask_calls["n"] == 2
    final_msg.assert_called_once()
    conn.close()


def test_abandon_confirmed_with_two_temps_lists_both_paths(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    first = dir_a / "out.hrpkg"
    second = dir_b / "out.hrpkg"
    t1 = dir_a / "out.hrpkg.11111111.partial"
    t2 = dir_b / "out.hrpkg.22222222.partial"
    t1.write_bytes(b"T1")
    t2.write_bytes(b"T2")
    deliver_n = {"n": 0}

    def fail_with_temps(wire_bytes: bytes, path: Path, *, reuse_complete_temp=None):
        deliver_n["n"] += 1
        if path == first:
            return DeliveryResult(complete_temp=t1, error=OSError("a locked"))
        return DeliveryResult(complete_temp=t2, error=OSError("b locked"))

    ask_n = {"n": 0}

    def ask(*, error, save_path):
        ask_n["n"] += 1
        return "relocate" if ask_n["n"] == 1 else "abandon"

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(),
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            side_effect=[(str(first), ""), (str(second), "")],
        ),
        patch("ui.transport_export_dialog.deliver_package", side_effect=fail_with_temps),
        patch.object(panel, "_ask_delivery_action", side_effect=ask),
        patch.object(panel, "_confirm_abandon", return_value=True),
        patch("ui.transport_export_dialog.QMessageBox.critical") as critical,
    ):
        panel._run_export()
    text = critical.call_args.args[2]
    assert str(t1.resolve()) in text
    assert str(t2.resolve()) in text
    assert "одного и того же пакета" in text
    assert t1.exists() and t1.read_bytes() == b"T1"
    assert t2.exists() and t2.read_bytes() == b"T2"
    assert deliver_n["n"] == 2
    conn.close()


def test_success_after_two_failed_attempts_no_leftover_partials(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"
    other = tmp_path / "subdir"
    other.mkdir()
    alt = other / "out.hrpkg"
    calls = {"n": 0}

    def flaky(wire_bytes: bytes, path: Path, *, reuse_complete_temp=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            temp = path.parent / f"{path.name}.{'a' * 8 if calls['n'] == 1 else 'b' * 8}.partial"
            temp.write_bytes(wire_bytes)
            return DeliveryResult(complete_temp=temp, error=OSError(f"fail{calls['n']}"))
        path.write_bytes(wire_bytes)
        return DeliveryResult(final_path=path)

    ask_n = {"n": 0}

    def ask(*, error, save_path):
        ask_n["n"] += 1
        return "relocate" if ask_n["n"] == 1 else "retry"

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(wire=b"final"),
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            side_effect=[(str(save_path), ""), (str(alt), "")],
        ),
        patch("ui.transport_export_dialog.deliver_package", side_effect=flaky),
        patch.object(panel, "_ask_delivery_action", side_effect=ask),
    ):
        panel._run_export()
    assert alt.read_bytes() == b"final"
    assert list(tmp_path.rglob("*.partial")) == []
    assert panel._stack.currentIndex() == 2
    conn.close()


def test_empty_package_confirmation_precedes_dialog(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path, preview_tables={})
    order: list[str] = []

    def note_question(*_args, **_kwargs):
        order.append("confirm")
        return QMessageBox.StandardButton.Yes

    def note_dialog(*_args, **_kwargs):
        order.append("dialog")
        return ("", "")

    with (
        patch.object(panel._operator, "export_personnel_package") as export_mock,
        patch(
            "ui.transport_export_dialog.QMessageBox.question",
            side_effect=note_question,
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            side_effect=note_dialog,
        ),
    ):
        panel._run_export()
    assert order == ["confirm", "dialog"]
    export_mock.assert_not_called()
    conn.close()


def test_empty_package_decline_skips_dialog_and_operator(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path, preview_tables={})
    with (
        patch.object(panel._operator, "export_personnel_package") as export_mock,
        patch(
            "ui.transport_export_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
        ) as dialog,
    ):
        panel._run_export()
    dialog.assert_not_called()
    export_mock.assert_not_called()
    conn.close()


@pytest.mark.parametrize(
    ("raw", "expected_name"),
    [
        ("out", "out.hrpkg"),
        ("out.txt", "out.txt.hrpkg"),
        ("отчёт v1.2", "отчёт v1.2.hrpkg"),
        ("out.hrpkg", "out.hrpkg"),
        ("out.HRPKG", "out.HRPKG"),
        ("x.hrpkg.hrpkg", "x.hrpkg.hrpkg"),
    ],
)
def test_hrpkg_suffix_normalized(qtbot, tmp_path: Path, raw: str, expected_name: str) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    chosen = tmp_path / raw
    expected = tmp_path / expected_name
    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(wire=b"abc"),
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(chosen), ""),
        ),
    ):
        panel._run_export()
    assert expected.read_bytes() == b"abc"
    assert list(tmp_path.glob(f"{expected_name}.*.partial")) == []
    conn.close()


def test_first_delivery_runtime_error_shows_dialog_no_slot_raise(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    save_path = tmp_path / "out.hrpkg"

    def boom(wire_bytes: bytes, path: Path, *, reuse_complete_temp=None):
        raise RuntimeError("unexpected delivery failure")

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(),
        ) as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(save_path), ""),
        ),
        patch("ui.transport_export_dialog.deliver_package", side_effect=boom),
        patch.object(panel, "_ask_delivery_action", return_value="abandon") as ask,
        patch.object(panel, "_confirm_abandon", return_value=True),
        patch.object(panel, "_show_abandon_final"),
    ):
        panel._run_export()  # must not raise
    export_mock.assert_called_once()
    ask.assert_called_once()
    assert isinstance(ask.call_args.kwargs["error"], RuntimeError)
    assert panel._stack.currentIndex() == 1
    conn.close()


def test_default_export_filename_strips_forbidden_chars() -> None:
    target = OutboundExportTarget(
        direction_id=9,
        peer_label='Peer\\A/B:C*D?E"F<G>H|I\x07',
        direction_status=DirectionStatus.ACTIVE,
        generation=0,
        accepted_sequence=0,
    )
    name = _default_export_filename(target)
    assert name.startswith("transport_")
    assert name.endswith(".hrpkg")
    assert "_dir9_" in name
    for ch in '\\/:*?"<>|\x07':
        assert ch not in name


def test_normalized_path_exists_confirm_no_then_yes(qtbot, tmp_path: Path) -> None:
    """Typed 'out' while out.hrpkg exists → confirm; No → dialog again; Yes → replace."""
    conn, panel = _panel_ready(qtbot, tmp_path)
    existing = tmp_path / "out.hrpkg"
    existing.write_bytes(b"OLD-PACKAGE")
    dialog_paths = iter([(str(tmp_path / "out"), ""), (str(tmp_path / "out"), "")])
    confirms = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(wire=b"NEW"),
        ) as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            side_effect=lambda *a, **k: next(dialog_paths),
        ),
        patch(
            "ui.transport_export_dialog.QMessageBox.question",
            side_effect=lambda *a, **k: next(confirms),
        ),
    ):
        panel._run_export()
    export_mock.assert_called_once()
    assert existing.read_bytes() == b"NEW"
    conn.close()


def test_dialog_returns_existing_hrpkg_no_extra_confirmation(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    existing = tmp_path / "out.hrpkg"
    existing.write_bytes(b"OLD")
    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(wire=b"NEW"),
        ) as export_mock,
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(existing), ""),
        ),
        patch.object(panel, "_confirm_replace_normalized_path") as confirm_replace,
    ):
        panel._run_export()
    export_mock.assert_called_once()
    confirm_replace.assert_not_called()
    assert existing.read_bytes() == b"NEW"
    conn.close()


def test_relocate_normalized_existing_confirm_no_skips_write(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    first = tmp_path / "first.hrpkg"
    other_dir = tmp_path / "d"
    other_dir.mkdir()
    existing = other_dir / "out.hrpkg"
    existing.write_bytes(b"KEEP")
    deliver_calls = {"n": 0}

    def fail_then_count(wire_bytes: bytes, path: Path, *, reuse_complete_temp=None):
        deliver_calls["n"] += 1
        return DeliveryResult(error=OSError("fail"))

    ask_n = {"n": 0}

    def ask(*, error, save_path):
        ask_n["n"] += 1
        if ask_n["n"] == 1:
            return "relocate"
        return "abandon"

    # Initial path, then relocate typed "out" (normalizes to existing out.hrpkg), then cancel
    dialogs = iter([(str(first), ""), (str(other_dir / "out"), ""), ("", "")])

    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=_personnel_result(),
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            side_effect=lambda *a, **k: next(dialogs),
        ),
        patch("ui.transport_export_dialog.deliver_package", side_effect=fail_then_count),
        patch.object(panel, "_ask_delivery_action", side_effect=ask),
        patch.object(
            panel,
            "_confirm_replace_normalized_path",
            return_value=False,
        ) as confirm,
        patch.object(panel, "_confirm_abandon", return_value=True),
        patch.object(panel, "_show_abandon_final"),
    ):
        panel._run_export()
    confirm.assert_called_once()
    assert deliver_calls["n"] == 1  # only first attempt; relocate write skipped
    assert existing.read_bytes() == b"KEEP"
    conn.close()


def test_abandon_final_singular_and_plural_wording(qtbot, tmp_path: Path) -> None:
    conn, panel = _panel_ready(qtbot, tmp_path)
    t1 = tmp_path / "out.hrpkg.11223344.partial"
    t2 = tmp_path / "out.hrpkg.55667788.partial"
    t1.write_bytes(b"x")
    t2.write_bytes(b"y")
    with patch("ui.transport_export_dialog.QMessageBox.critical") as critical:
        panel._show_abandon_final([TrackedTemp(path=t1, for_save_path=tmp_path / "out.hrpkg")])
        singular = critical.call_args.args[2]
        panel._show_abandon_final(
            [
                TrackedTemp(path=t1, for_save_path=tmp_path / "out.hrpkg"),
                TrackedTemp(path=t2, for_save_path=tmp_path / "other.hrpkg"),
            ]
        )
        plural = critical.call_args.args[2]
    assert "Единственная копия пакета" in singular
    assert str(t1.resolve()) in singular
    assert "одного и того же пакета" in plural
    assert str(t1.resolve()) in plural and str(t2.resolve()) in plural
    conn.close()
