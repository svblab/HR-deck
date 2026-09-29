"""Single peer installation handle (isolated data dir + service graph)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from data.db import Connection
from data.import_sessions import ImportSessionRepository
from data.paths import default_db_path, ensure_user_data_dirs
from services.backup import BackupService
from services.bootstrap import BootstrapService
from services.directories import DirectoryService
from services.directory_sync import DirectorySyncService
from services.employee_conversion import EmployeeConversionService
from services.employees import EmployeeService
from services.import_conversion_ingest import ImportConversionIngestService
from services.status_clarification import StatusClarificationService
from services.status_history import StatusHistoryService
from services.transport_export import TransportExportAdminService
from services.transport_import_inbound import TransportInboundImportService
from services.transport_key_admin import TransportKeyAdminService
from services.transport_keys import TransportKeyStore
from tests.e2e_mechanics.clock import ScenarioClock
from tests.e2e_mechanics.oob import DuplexDirections


@dataclass
class OrgIds:
    branch_id: int
    department_id: int
    division_id: int
    position_id: int
    employment_type_id: int = 1


@dataclass
class Peer:
    """One independent installation with its own SQLCipher DB and master key."""

    label: str
    data_dir: Path
    db_path: Path
    conn: Connection
    session: Any
    clock: ScenarioClock
    directions: DuplexDirections | None = None
    org: OrgIds | None = None
    backup_path: Path | None = None
    _post_bootstrap_snapshot: dict[str, Any] = field(default_factory=dict)

    # services (rebuilt after restore)
    directories: DirectoryService | None = None
    employees: EmployeeService | None = None
    statuses: StatusHistoryService | None = None
    clarify: StatusClarificationService | None = None
    backup: BackupService | None = None
    key_admin: TransportKeyAdminService | None = None
    store: TransportKeyStore | None = None
    sync: DirectorySyncService | None = None
    exporter: TransportExportAdminService | None = None
    inbound: TransportInboundImportService | None = None
    conversion: EmployeeConversionService | None = None
    ingest: ImportConversionIngestService | None = None
    sessions: ImportSessionRepository | None = None

    def wire_services(self) -> None:
        assert self.session is not None
        clock = self.clock
        self.directories = DirectoryService(self.conn, self.session, clock=clock)
        self.employees = EmployeeService(self.conn, self.session, clock=clock)
        self.statuses = StatusHistoryService(self.conn, self.session, clock=clock)
        self.clarify = StatusClarificationService(self.conn, self.session, clock=clock)
        self.backup = BackupService(
            self.conn, self.session, db_path=self.db_path, clock=clock
        )
        self.store = TransportKeyStore(self.conn, clock=clock)
        self.key_admin = TransportKeyAdminService(
            self.conn, self.session, clock=clock
        )
        self.sync = DirectorySyncService(self.conn, self.session)
        self.exporter = TransportExportAdminService(
            self.conn, self.session, store=self.store
        )
        self.inbound = TransportInboundImportService(
            self.conn,
            self.session,
            store=self.store,
            clock=clock,
            db_path=self.db_path,
        )
        self.sessions = ImportSessionRepository(self.conn)
        self.ingest = ImportConversionIngestService(
            self.conn, self.session, sessions=self.sessions, clock=clock
        )
        self.conversion = EmployeeConversionService(
            self.conn,
            self.session,
            self.employees,
            sessions=self.sessions,
            db_path=self.db_path,
        )

    def ensure_org(self, *, branch_name: str) -> OrgIds:
        assert self.directories is not None
        branches = self.directories.list_branches(active_only=True)
        if branches:
            branch_id = branches[0].id
        else:
            branch_id = self.directories.create_branch(branch_name)
        deps = self.directories.list_departments(branch_id=branch_id, active_only=True)
        department_id = (
            deps[0].id
            if deps
            else self.directories.create_department(branch_id, f"Dept {self.label}")
        )
        divs = self.directories.list_divisions(
            branch_id=branch_id, department_id=department_id, active_only=True
        )
        division_id = (
            divs[0].id
            if divs
            else self.directories.create_division(
                branch_id, department_id, f"Div {self.label}"
            )
        )
        positions = self.directories.list_positions(branch_id=branch_id, active_only=True)
        position_id = (
            positions[0].id
            if positions
            else self.directories.create_position(branch_id, f"Engineer {self.label}")
        )
        self.org = OrgIds(
            branch_id=branch_id,
            department_id=department_id,
            division_id=division_id,
            position_id=position_id,
        )
        return self.org

    def capture_transport_snapshot(self) -> dict[str, list[tuple[Any, ...]]]:
        c = self.conn
        return {
            "installation": c.execute(
                "SELECT installation_id, display_label FROM transport_installation"
                " ORDER BY installation_id"
            ).fetchall(),
            "peer_trust": c.execute(
                "SELECT peer_installation_id, signing_trust_status,"
                " bootstrap_trust_status FROM transport_peer_trust ORDER BY id"
            ).fetchall(),
            "direction_state": c.execute(
                "SELECT sender_installation_id, recipient_installation_id,"
                " generation, accepted_sequence, current_wk_id, direction_status"
                " FROM transport_direction_state ORDER BY id"
            ).fetchall(),
            "wk_count": c.execute("SELECT COUNT(*) FROM transport_wk_keys").fetchone(),
            "package_count": c.execute(
                "SELECT COUNT(*) FROM transport_package_records"
            ).fetchone(),
            "employee_count": c.execute(
                "SELECT COUNT(*) FROM employees WHERE is_archived=0"
            ).fetchone(),
            "status_history_count": c.execute(
                "SELECT COUNT(*) FROM status_history"
            ).fetchone(),
        }

    def business_fingerprint(self) -> dict[str, Any]:
        return {
            "employees": self.conn.execute(
                "SELECT external_id, full_name, is_archived FROM employees"
                " ORDER BY external_id"
            ).fetchall(),
            "branches": self.conn.execute(
                "SELECT external_id, name, is_archived FROM branches ORDER BY external_id"
            ).fetchall(),
            "transport": self.capture_transport_snapshot(),
        }

    def reconnect_after_restore(self, new_conn: Connection) -> None:
        self.conn = new_conn
        self.wire_services()


def open_peer(
    *,
    label: str,
    data_dir: Path,
    clock: ScenarioClock,
    login: str,
    password: str,
) -> Peer:
    ensure_user_data_dirs(data_dir)
    db_path = default_db_path(data_dir)
    conn, session, _recovery = BootstrapService(clock=clock).initial_administrator_setup(
        db_path=db_path,
        login=login,
        password=password,
    )
    # Headless long runs: disable UI idle lock (default 900s clears master_key).
    session.inactivity_timeout_enabled = False
    session.touch()
    # Label local installation for diagnostics.
    store = TransportKeyStore(conn, clock=clock)
    store.ensure_local_installation(display_label=label)
    conn.commit()
    peer = Peer(
        label=label,
        data_dir=data_dir,
        db_path=db_path,
        conn=conn,
        session=session,
        clock=clock,
    )
    peer.wire_services()
    return peer

