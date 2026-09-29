"""Режим демо: временная БД с синтетическими данными для презентации заказчику.

Не затрагивает рабочий каталог данных пользователя.
Учётные данные только в demo-БД: login=demo / password=demo.

Даты статусов привязаны к date.today() (UTC-календарь), чтобы доска
оставалась согласованной в любой день показа. При каждом запуске --demo
база в demo-каталоге пересоздаётся (force reset).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from data.backup_io import prepare_database_startup
from data.db import Connection, table_columns
from data.keywrap import keywrap_path_for
from data.paths import ensure_user_data_dirs
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.status_history import StatusHistoryService

logger = logging.getLogger(__name__)

DEMO_LOGIN = "demo"
DEMO_PASSWORD = "demo"
DEMO_COMPANY_NAME = "Демо-компания (синтетика)"
DEMO_EMPLOYEE_COUNT = 18


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _today() -> date:
    return datetime.now(UTC).date()


def _new_external_id() -> str:
    return str(uuid.uuid4())


def _has_external(conn: Connection, table: str) -> bool:
    return "external_id" in table_columns(conn, table)


def _insert_branch(conn: Connection, *, branch_id: int, name: str, now: str) -> None:
    if _has_external(conn, "branches"):
        conn.execute(
            "INSERT INTO branches ("
            " id, external_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?)",
            (branch_id, _new_external_id(), name, now, now),
        )
    else:
        conn.execute(
            "INSERT INTO branches (id, name, is_archived, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (branch_id, name, now, now),
        )


def _insert_department(
    conn: Connection, *, dept_id: int, branch_id: int, name: str, now: str
) -> None:
    if _has_external(conn, "departments"):
        conn.execute(
            "INSERT INTO departments ("
            " id, external_id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, 0, ?, ?)",
            (dept_id, _new_external_id(), branch_id, name, now, now),
        )
    else:
        conn.execute(
            "INSERT INTO departments ("
            " id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?)",
            (dept_id, branch_id, name, now, now),
        )


def _insert_division(
    conn: Connection,
    *,
    division_id: int,
    branch_id: int,
    department_id: int | None,
    name: str,
    now: str,
) -> None:
    cols = table_columns(conn, "divisions")
    has_ext = "external_id" in cols
    has_branch = "branch_id" in cols
    if has_branch and has_ext:
        conn.execute(
            "INSERT INTO divisions ("
            " id, external_id, branch_id, department_id, name, is_archived,"
            " created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (division_id, _new_external_id(), branch_id, department_id, name, now, now),
        )
    elif has_branch:
        conn.execute(
            "INSERT INTO divisions ("
            " id, branch_id, department_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, 0, ?, ?)",
            (division_id, branch_id, department_id, name, now, now),
        )
    else:
        conn.execute(
            "INSERT INTO divisions ("
            " id, department_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?)",
            (division_id, department_id, name, now, now),
        )


def _insert_position(
    conn: Connection, *, position_id: int, branch_id: int | None, name: str, now: str
) -> None:
    cols = table_columns(conn, "positions")
    has_ext = "external_id" in cols
    has_branch = "branch_id" in cols
    if has_branch and has_ext:
        conn.execute(
            "INSERT INTO positions ("
            " id, external_id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, 0, ?, ?)",
            (position_id, _new_external_id(), branch_id, name, now, now),
        )
    elif has_branch:
        conn.execute(
            "INSERT INTO positions ("
            " id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?)",
            (position_id, branch_id, name, now, now),
        )
    else:
        conn.execute(
            "INSERT INTO positions (id, name, is_archived, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (position_id, name, now, now),
        )


def _insert_employee(
    conn: Connection,
    *,
    emp_id: int,
    full_name: str,
    position_id: int,
    branch_id: int,
    department_id: int | None,
    division_id: int | None,
    employment_type_id: int,
    hire_date: str,
    note: str,
    now: str,
) -> None:
    cols = table_columns(conn, "employees")
    has_ext = "external_id" in cols
    if has_ext:
        conn.execute(
            "INSERT INTO employees ("
            " id, external_id, full_name, position_id, branch_id, department_id,"
            " division_id, employment_type_id, note, hire_date, contacts,"
            " home_address, social_insurance_number, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (
                emp_id,
                _new_external_id(),
                full_name,
                position_id,
                branch_id,
                department_id,
                division_id,
                employment_type_id,
                note,
                hire_date,
                f"+7-900-100-{emp_id:02d}-00",
                f"г. Тестовск, ул. Демо, {emp_id}",
                f"000-000-000 {emp_id:02d}",
                now,
                now,
            ),
        )
    else:
        conn.execute(
            "INSERT INTO employees ("
            " id, full_name, position_id, branch_id, department_id, division_id,"
            " employment_type_id, note, hire_date, contacts, home_address,"
            " social_insurance_number, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (
                emp_id,
                full_name,
                position_id,
                branch_id,
                department_id,
                division_id,
                employment_type_id,
                note,
                hire_date,
                f"+7-900-100-{emp_id:02d}-00",
                f"г. Тестовск, ул. Демо, {emp_id}",
                f"000-000-000 {emp_id:02d}",
                now,
                now,
            ),
        )


def seed_demo_org(conn: Connection, *, now: str | None = None) -> dict[str, int]:
    """Заполнить оргструктуру и 18 сотрудников. Вызывать после миграций."""
    now = now or _utc_now_iso()
    _insert_branch(conn, branch_id=1, name="Центральный офис", now=now)
    _insert_branch(conn, branch_id=2, name="Филиал Север", now=now)

    _insert_department(conn, dept_id=1, branch_id=1, name="Департамент разработки", now=now)
    _insert_department(conn, dept_id=2, branch_id=1, name="Департамент продаж", now=now)
    _insert_department(conn, dept_id=3, branch_id=2, name="Производство", now=now)

    _insert_division(
        conn, division_id=1, branch_id=1, department_id=1, name="Отдел платформы", now=now
    )
    _insert_division(
        conn, division_id=2, branch_id=1, department_id=1, name="Отдел QA", now=now
    )
    _insert_division(
        conn,
        division_id=3,
        branch_id=1,
        department_id=2,
        name="Отдел ключевых клиентов",
        now=now,
    )
    _insert_division(
        conn, division_id=4, branch_id=2, department_id=3, name="Цех сборки", now=now
    )

    _insert_position(conn, position_id=1, branch_id=1, name="Инженер", now=now)
    _insert_position(conn, position_id=2, branch_id=1, name="Аналитик", now=now)
    _insert_position(conn, position_id=3, branch_id=1, name="Менеджер по продажам", now=now)
    _insert_position(conn, position_id=4, branch_id=2, name="Мастер смены", now=now)
    _insert_position(conn, position_id=5, branch_id=1, name="Руководитель отдела", now=now)

    people: list[tuple] = [
        (1, "Иванов Иван Иванович", 1, 1, 1, 1, 1, "2023-03-01", ""),
        (2, "Петрова Анна Сергеевна", 2, 1, 1, 1, 1, "2022-06-15", ""),
        (3, "Сидоров Алексей Петрович", 1, 1, 1, 2, 1, "2024-01-10", ""),
        (4, "Козлова Мария Дмитриевна", 5, 1, 1, 1, 1, "2020-09-01", "руководитель"),
        (5, "Смирнов Дмитрий Олегович", 3, 1, 2, 3, 1, "2021-11-20", ""),
        (6, "Васильева Елена Игоревна", 3, 1, 2, 3, 1, "2023-05-05", ""),
        (7, "Морозов Павел Андреевич", 4, 2, 3, 4, 1, "2019-02-14", ""),
        (8, "Новикова Ольга Викторовна", 4, 2, 3, 4, 1, "2022-08-01", ""),
        (9, "Фёдоров Никита Алексеевич", 1, 1, 1, 1, 2, "2025-01-15", "временный"),
        (10, "Орлова Татьяна Михайловна", 2, 1, 1, 2, 1, "2024-04-01", ""),
        (11, "Лебедев Артём Сергеевич", 1, 1, 1, 1, 3, "2025-06-01", "подрядчик"),
        (12, "Соколова Ирина Павловна", 3, 1, 2, 3, 1, "2021-03-12", ""),
        (13, "Кузнецов Максим Евгеньевич", 4, 2, 3, 4, 1, "2020-07-20", ""),
        (14, "Попова Юлия Андреевна", 2, 1, 1, 1, 1, "2023-09-01", ""),
        (15, "Волков Сергей Николаевич", 1, 1, 1, 2, 1, "2022-12-01", ""),
        (16, "Алексеева Наталья Олеговна", 5, 1, 2, 3, 1, "2018-04-15", "руководитель"),
        (17, "Григорьев Илья Романович", 1, 1, 1, 1, 1, "2024-07-01", ""),
        (18, "Зайцева Дарья Константиновна", 3, 1, 2, 3, 2, "2025-02-10", "временный"),
    ]

    for row in people:
        _insert_employee(
            conn,
            emp_id=row[0],
            full_name=row[1],
            position_id=row[2],
            branch_id=row[3],
            department_id=row[4],
            division_id=row[5],
            employment_type_id=row[6],
            hire_date=row[7],
            note=row[8],
            now=now,
        )

    conn.commit()
    return {
        "branch_central": 1,
        "branch_north": 2,
        "employee_count": len(people),
    }


def _assign_demo_statuses(
    conn: Connection,
    session: SessionState,
    *,
    today: date | None = None,
    now: str | None = None,
) -> None:
    """Назначить статусы относительно «сегодня» (UTC date)."""
    today = today or _today()
    now = now or _utc_now_iso()
    svc = StatusHistoryService(conn, session, clock=lambda: now)

    # (emp_id, status_id, start_offset_days, end_offset_days | None)
    plan: list[tuple[int, int, int, int | None]] = [
        (1, 1, -27, None),
        (2, 2, -27, None),
        (3, 5, -8, 7),
        (4, 1, -44, None),
        (5, 3, -3, 4),
        (6, 1, -27, None),
        (7, 1, -27, None),
        (8, 4, -6, 2),
        (9, 2, -18, None),
        (10, 1, -27, None),
        (11, 1, -27, None),
        (12, 6, -1, -1),
        (13, 1, -27, None),
        (14, 5, -13, -2),
        (15, 1, -89, -8),
        (16, 1, -27, None),
        (17, 2, -27, None),
        (18, 1, -27, None),
    ]

    errors: list[str] = []
    for emp_id, status_id, start_off, end_off in plan:
        start = (today + timedelta(days=start_off)).isoformat()
        end = None if end_off is None else (today + timedelta(days=end_off)).isoformat()
        try:
            svc.assign_status(
                emp_id,
                status_id=status_id,
                start_date=start,
                end_date=end,
                confirmed=True,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"emp={emp_id} status={status_id}: {exc}"
            logger.error("demo status assign failed: %s", msg)
            errors.append(msg)

    try:
        svc.assign_status(
            1,
            status_id=5,
            start_date=(today + timedelta(days=14)).isoformat(),
            end_date=(today + timedelta(days=28)).isoformat(),
            note="плановый отпуск",
            confirmed=True,
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"future vacation emp=1: {exc}"
        logger.error("demo future status failed: %s", msg)
        errors.append(msg)

    if errors:
        raise RuntimeError(
            "demo status seed failed (" + str(len(errors)) + "): " + "; ".join(errors[:3])
        )


def reset_demo_database(db_path: Path) -> None:
    """Удалить demo-БД и keywrap, чтобы следующий prepare собрал seed заново."""
    path = Path(db_path)
    targets = (
        path,
        keywrap_path_for(path),
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
    )
    for item in targets:
        if item.is_file():
            item.unlink()
            logger.info("demo reset removed %s", item)


def _disable_demo_idle_lock(
    conn: Connection,
    session: SessionState,
    db_path: Path,
    now: str,
) -> None:
    """Записать отключение автоблокировки в базу, не только в объект сессии."""
    mgr = AccountManagementService(conn, session, db_path=db_path, clock=lambda: now)
    mgr.update_security_settings(
        inactivity_timeout_enabled=False,
        inactivity_timeout_seconds=0,
    )


def launch_demo_database(db_path: Path) -> tuple[Connection, SessionState]:
    """Сбросить файл, затем проверить его и собрать demo-БД.

    Сброс идёт до prepare_database_startup: повреждённый файл не блокирует показ.
    """
    path = Path(db_path)
    ensure_user_data_dirs(path.parent)
    reset_demo_database(path)
    prepare_database_startup(path)
    return prepare_demo_database(path, force_reset=False)


def prepare_demo_database(
    db_path: Path,
    *,
    force_reset: bool = True,
) -> tuple[Connection, SessionState]:
    """
    Подготовить demo-БД: bootstrap + seed + статусы.

    По умолчанию force_reset=True — каждый запуск --demo пересоздаёт базу,
    чтобы даты статусов совпадали с «сегодня» и не оставался битый seed.
    """
    path = Path(db_path)
    ensure_user_data_dirs(path.parent)

    if force_reset:
        reset_demo_database(path)

    now = _utc_now_iso()
    today = _today()

    bootstrap = BootstrapService(clock=lambda: now)
    if bootstrap.needs_setup(path):
        conn, session, _recovery = bootstrap.initial_administrator_setup(
            db_path=path,
            login=DEMO_LOGIN,
            password=DEMO_PASSWORD,
        )
        logger.info("demo bootstrap complete: login=%s", DEMO_LOGIN)
    else:
        from services.authentication import AuthenticationService

        auth = AuthenticationService(clock=lambda: now)
        conn, session = auth.login(
            db_path=path,
            login=DEMO_LOGIN,
            password=DEMO_PASSWORD,
        )
        logger.info("demo login to existing DB")

    count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    mgr = AccountManagementService(conn, session, db_path=path, clock=lambda: now)
    if count == 0:
        seed_demo_org(conn, now=now)
        _assign_demo_statuses(conn, session, today=today, now=now)
        mgr.update_company_profile(company_name=DEMO_COMPANY_NAME)
        logger.info("demo org seeded: %s employees as of %s", DEMO_EMPLOYEE_COUNT, today)
    else:
        logger.info("demo DB already has %s employees — skip seed", count)

    _disable_demo_idle_lock(conn, session, path, now)
    return conn, session


def demo_data_dir() -> Path:
    """Каталог данных для режима демо (не пересекается с рабочей установкой)."""
    import tempfile

    base = Path(tempfile.gettempdir()) / "personnel-availability-demo"
    base.mkdir(parents=True, exist_ok=True)
    return base


def demo_db_path() -> Path:
    return demo_data_dir() / "personnel.db"
