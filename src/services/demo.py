"""Режим демо: временная БД с синтетическими данными для презентации заказчику.

Не затрагивает рабочий каталог данных пользователя.
Учётные данные только в demo-БД: login=demo / password=demo.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from pathlib import Path

from data.db import Connection, table_columns
from data.paths import ensure_user_data_dirs
from services.account_management import AccountManagementService
from services.bootstrap import BootstrapService
from services.session import SessionState
from services.status_history import StatusHistoryService

logger = logging.getLogger(__name__)

DEMO_LOGIN = "demo"
DEMO_PASSWORD = "demo"
DEMO_COMPANY_NAME = "Демо-компания (синтетика)"

_NOW = "2026-09-28T09:00:00Z"
_TODAY = date(2026, 9, 28)


def _new_external_id() -> str:
    return str(uuid.uuid4())


def _has_external(conn: Connection, table: str) -> bool:
    return "external_id" in table_columns(conn, table)


def _insert_branch(conn: Connection, *, branch_id: int, name: str) -> None:
    if _has_external(conn, "branches"):
        conn.execute(
            "INSERT INTO branches ("
            " id, external_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?)",
            (branch_id, _new_external_id(), name, _NOW, _NOW),
        )
    else:
        conn.execute(
            "INSERT INTO branches (id, name, is_archived, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (branch_id, name, _NOW, _NOW),
        )


def _insert_department(
    conn: Connection, *, dept_id: int, branch_id: int, name: str
) -> None:
    if _has_external(conn, "departments"):
        conn.execute(
            "INSERT INTO departments ("
            " id, external_id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, 0, ?, ?)",
            (dept_id, _new_external_id(), branch_id, name, _NOW, _NOW),
        )
    else:
        conn.execute(
            "INSERT INTO departments ("
            " id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?)",
            (dept_id, branch_id, name, _NOW, _NOW),
        )


def _insert_division(
    conn: Connection,
    *,
    division_id: int,
    branch_id: int,
    department_id: int | None,
    name: str,
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
            (
                division_id,
                _new_external_id(),
                branch_id,
                department_id,
                name,
                _NOW,
                _NOW,
            ),
        )
    elif has_branch:
        conn.execute(
            "INSERT INTO divisions ("
            " id, branch_id, department_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, 0, ?, ?)",
            (division_id, branch_id, department_id, name, _NOW, _NOW),
        )
    else:
        conn.execute(
            "INSERT INTO divisions ("
            " id, department_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?)",
            (division_id, department_id, name, _NOW, _NOW),
        )


def _insert_position(
    conn: Connection, *, position_id: int, branch_id: int | None, name: str
) -> None:
    cols = table_columns(conn, "positions")
    has_ext = "external_id" in cols
    has_branch = "branch_id" in cols
    if has_branch and has_ext:
        conn.execute(
            "INSERT INTO positions ("
            " id, external_id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, 0, ?, ?)",
            (position_id, _new_external_id(), branch_id, name, _NOW, _NOW),
        )
    elif has_branch:
        conn.execute(
            "INSERT INTO positions ("
            " id, branch_id, name, is_archived, created_at, updated_at"
            ") VALUES (?, ?, ?, 0, ?, ?)",
            (position_id, branch_id, name, _NOW, _NOW),
        )
    else:
        conn.execute(
            "INSERT INTO positions (id, name, is_archived, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (position_id, name, _NOW, _NOW),
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
    note: str = "",
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
                _NOW,
                _NOW,
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
                _NOW,
                _NOW,
            ),
        )


def seed_demo_org(conn: Connection) -> dict[str, int]:
    """
    Заполнить оргструктуру и ~18 сотрудников с разными статусами.

    Возвращает ключевые id. Вызывать после миграций.
    """
    _insert_branch(conn, branch_id=1, name="Центральный офис")
    _insert_branch(conn, branch_id=2, name="Филиал Север")

    _insert_department(conn, dept_id=1, branch_id=1, name="Департамент разработки")
    _insert_department(conn, dept_id=2, branch_id=1, name="Департамент продаж")
    _insert_department(conn, dept_id=3, branch_id=2, name="Производство")

    _insert_division(
        conn, division_id=1, branch_id=1, department_id=1, name="Отдел платформы"
    )
    _insert_division(
        conn, division_id=2, branch_id=1, department_id=1, name="Отдел QA"
    )
    _insert_division(
        conn, division_id=3, branch_id=1, department_id=2, name="Отдел ключевых клиентов"
    )
    _insert_division(
        conn, division_id=4, branch_id=2, department_id=3, name="Цех сборки"
    )

    _insert_position(conn, position_id=1, branch_id=1, name="Инженер")
    _insert_position(conn, position_id=2, branch_id=1, name="Аналитик")
    _insert_position(conn, position_id=3, branch_id=1, name="Менеджер по продажам")
    _insert_position(conn, position_id=4, branch_id=2, name="Мастер смены")
    _insert_position(conn, position_id=5, branch_id=1, name="Руководитель отдела")

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
        )

    conn.commit()
    return {
        "branch_central": 1,
        "branch_north": 2,
        "employee_count": len(people),
    }


def _assign_demo_statuses(conn: Connection, session: SessionState) -> None:
    """Назначить текущие и плановые статусы через сервис (с аудитом)."""
    svc = StatusHistoryService(conn, session, clock=lambda: _NOW)

    # status_id: 1 office, 2 remote, 3 trip, 4 sick, 5 vacation, 6 day_off
    assignments: list[tuple[int, int, str, str | None]] = [
        (1, 1, "2026-09-01", None),
        (2, 2, "2026-09-01", None),
        (3, 5, "2026-09-20", "2026-10-05"),
        (4, 1, "2026-08-15", None),
        (5, 3, "2026-09-25", "2026-10-02"),
        (6, 1, "2026-09-01", None),
        (7, 1, "2026-09-01", None),
        (8, 4, "2026-09-22", "2026-09-30"),
        (9, 2, "2026-09-10", None),
        (10, 1, "2026-09-01", None),
        (11, 1, "2026-09-01", None),
        (12, 6, "2026-09-27", "2026-09-27"),
        (13, 1, "2026-09-01", None),
        (14, 5, "2026-09-15", "2026-09-26"),
        (15, 1, "2026-07-01", "2026-09-20"),
        (16, 1, "2026-09-01", None),
        (17, 2, "2026-09-01", None),
        (18, 1, "2026-09-01", None),
    ]

    for emp_id, status_id, start, end in assignments:
        try:
            svc.assign_status(
                emp_id,
                status_id=status_id,
                start_date=start,
                end_date=end,
                confirmed=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("demo status assign emp=%s failed: %s", emp_id, exc)

    try:
        svc.assign_status(
            1,
            status_id=5,
            start_date=(_TODAY + timedelta(days=14)).isoformat(),
            end_date=(_TODAY + timedelta(days=28)).isoformat(),
            note="плановый отпуск",
            confirmed=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("demo future status failed: %s", exc)


def prepare_demo_database(db_path: Path) -> tuple[Connection, SessionState]:
    """
    Подготовить demo-БД: bootstrap (если нужно) + seed + статусы.

    Возвращает открытую (conn, session) уже залогиненную как demo-админ.
    """
    path = Path(db_path)
    ensure_user_data_dirs(path.parent)

    bootstrap = BootstrapService(clock=lambda: _NOW)
    if bootstrap.needs_setup(path):
        conn, session, _recovery = bootstrap.initial_administrator_setup(
            db_path=path,
            login=DEMO_LOGIN,
            password=DEMO_PASSWORD,
        )
        logger.info("demo bootstrap complete: login=%s", DEMO_LOGIN)
    else:
        from services.authentication import AuthenticationService

        auth = AuthenticationService(clock=lambda: _NOW)
        conn, session = auth.login(
            db_path=path,
            login=DEMO_LOGIN,
            password=DEMO_PASSWORD,
        )
        logger.info("demo login to existing DB")

    count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    if count == 0:
        seed_demo_org(conn)
        _assign_demo_statuses(conn, session)
        try:
            mgr = AccountManagementService(
                conn, session, db_path=path, clock=lambda: _NOW
            )
            mgr.update_company_profile(company_name=DEMO_COMPANY_NAME)
        except Exception as exc:  # noqa: BLE001
            logger.warning("demo company profile: %s", exc)
        logger.info("demo org seeded")
    else:
        logger.info("demo DB already has %s employees — skip seed", count)

    return conn, session


def demo_data_dir() -> Path:
    """Каталог данных для режима демо (не пересекается с рабочей установкой)."""
    import tempfile

    base = Path(tempfile.gettempdir()) / "personnel-availability-demo"
    base.mkdir(parents=True, exist_ok=True)
    return base


def demo_db_path() -> Path:
    return demo_data_dir() / "personnel.db"
