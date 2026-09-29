"""UI: transport export panel (Issue #130)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from domain.transport import DirectionStatus
from services.bootstrap import BootstrapService
from services.employees import EmployeeService
from services.transport_export import TransportExportResult
from services.transport_operator import OutboundExportTarget, PersonnelTransportExportResult
from ui.transport_export_dialog import TransportExportPanel

_T0 = "2026-09-29T15:00:00Z"


def _open(tmp_path: Path):
    db = tmp_path / "app.db"
    conn, session, _ = BootstrapService(clock=lambda: _T0).initial_administrator_setup(
        db_path=db, login="admin", password="AdminPass-1"
    )
    employees = EmployeeService(conn, session, clock=lambda: _T0)
    return conn, session, employees, db


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
    panel._preview_tables = {"branches": [{}]}
    panel._stack.setCurrentIndex(1)
    export_result = TransportExportResult(
        package=MagicMock(),
        wire_bytes=b"wire-bytes",
        package_id="pkg-1",
        generation=0,
        sequence=1,
        direction_id=1,
    )
    personnel = PersonnelTransportExportResult(
        export=export_result,
        tables_exported=("branches",),
        payload_empty=False,
    )
    save_path = tmp_path / "out.hrpkg"
    with (
        patch.object(
            panel._operator,
            "export_personnel_package",
            return_value=personnel,
        ),
        patch(
            "ui.transport_export_dialog.QFileDialog.getSaveFileName",
            return_value=(str(save_path), ""),
        ),
    ):
        panel._run_export()
    assert save_path.read_bytes() == b"wire-bytes"
    assert panel._stack.currentIndex() == 2
    conn.close()
