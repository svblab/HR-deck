"""Синтетические данные для тестов (ANCHOR_PROTOCOL §9) — вымышленная компания."""

from __future__ import annotations

from data.db import Connection, table_columns

_NOW = "2026-08-01T10:00:00Z"


def _insert_division(
    conn: Connection,
    *,
    division_id: int,
    branch_id: int,
    department_id: int,
    name: str,
) -> None:
    if "branch_id" in table_columns(conn, "divisions"):
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
    conn: Connection,
    *,
    position_id: int,
    branch_id: int,
    name: str,
) -> None:
    if "branch_id" in table_columns(conn, "positions"):
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


def seed_synthetic_org(conn: Connection) -> dict[str, int]:
    """
    Заполнить справочники и двух сотрудников с одинаковым ФИО (разные ID).

    Возвращает словарь ключевых id для тестов.
    """
    conn.execute(
        "INSERT INTO branches (id, name, is_archived, created_at, updated_at) "
        "VALUES (1, ?, 0, ?, ?)",
        ("Филиал Север (тест)", _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO departments (id, branch_id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 1, ?, 0, ?, ?)",
        ("Департамент разработки", _NOW, _NOW),
    )
    _insert_division(
        conn,
        division_id=1,
        branch_id=1,
        department_id=1,
        name="Отдел платформы",
    )
    _insert_position(conn, position_id=1, branch_id=1, name="Инженер")
    _insert_position(conn, position_id=2, branch_id=1, name="Аналитик")

    # Два сотрудника с одним ФИО — идентификация по ID (ТЗ §3.1 / TESTING 2.6).
    conn.execute(
        "INSERT INTO employees ("
        " id, full_name, position_id, branch_id, department_id, division_id,"
        " employment_type_id, note, hire_date, contacts, home_address,"
        " social_insurance_number, is_archived, created_at, updated_at"
        ") VALUES (1, ?, 1, 1, 1, 1, 1, ?, ?, ?, ?, ?, 0, ?, ?)",
        (
            "Иванов Иван Иванович",
            "синтетика",
            "2024-01-15",
            "+7-900-000-00-01",
            "г. Тестовск, ул. Фиктивная, 1",
            "000-000-000 01",
            _NOW,
            _NOW,
        ),
    )
    conn.execute(
        "INSERT INTO employees ("
        " id, full_name, position_id, branch_id, department_id, division_id,"
        " employment_type_id, note, hire_date, contacts, home_address,"
        " social_insurance_number, is_archived, created_at, updated_at"
        ") VALUES (2, ?, 2, 1, 1, 1, 2, ?, ?, ?, ?, ?, 0, ?, ?)",
        (
            "Иванов Иван Иванович",
            "синтетика-дубль-фио",
            "2025-03-01",
            "+7-900-000-00-02",
            "г. Тестовск, ул. Фиктивная, 2",
            "000-000-000 02",
            _NOW,
            _NOW,
        ),
    )
    conn.commit()
    return {
        "branch_id": 1,
        "department_id": 1,
        "division_id": 1,
        "position_engineer_id": 1,
        "position_analyst_id": 2,
        "employee_a_id": 1,
        "employee_b_id": 2,
    }
