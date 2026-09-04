"""Генератор синтетической базы для нагрузочной приёмки (EPIC-016 / TESTING §2.8).

Не хранит построчные данные в репозитории — создаёт зашифрованную БД по запросу.
"""

from __future__ import annotations

import argparse
from pathlib import Path

_NOW = "2026-08-01T10:00:00Z"
_DEFAULT_COUNT = 400


def seed_perf_org(conn) -> dict[str, int]:
    """Справочники оргструктуры для нагрузочной фикстуры."""
    conn.execute(
        "INSERT INTO branches (id, name, is_archived, created_at, updated_at) "
        "VALUES (1, ?, 0, ?, ?)",
        ("Филиал Нагрузка (тест)", _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO departments (id, branch_id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 1, ?, 0, ?, ?)",
        ("Департамент нагрузочного теста", _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO divisions (id, department_id, name, is_archived, created_at, updated_at) "
        "VALUES (1, 1, ?, 0, ?, ?)",
        ("Отдел синтетики", _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO positions (id, name, is_archived, created_at, updated_at) "
        "VALUES (1, ?, 0, ?, ?)",
        ("Инженер", _NOW, _NOW),
    )
    conn.execute(
        "INSERT INTO positions (id, name, is_archived, created_at, updated_at) "
        "VALUES (2, ?, 0, ?, ?)",
        ("Аналитик", _NOW, _NOW),
    )
    return {
        "branch_id": 1,
        "department_id": 1,
        "division_id": 1,
        "position_engineer_id": 1,
        "position_analyst_id": 2,
    }


def seed_perf_dataset(
    conn,
    *,
    employee_count: int = _DEFAULT_COUNT,
    account_id: int = 1,
) -> dict[str, int]:
    """
    Заполнить БД ``employee_count`` синтетическими сотрудниками и историей статусов.

    Предполагает: миграции применены; учётная запись ``account_id`` существует
    (обычно после ``BootstrapService.initial_administrator_setup``).
    """
    if employee_count < 1:
        raise ValueError("employee_count must be >= 1")

    org = seed_perf_org(conn)
    rows: list[tuple] = []
    for i in range(1, employee_count + 1):
        rows.append(
            (
                i,
                f"Тестов Тест Т{i:03d}",
                1 if i % 2 else 2,
                org["branch_id"],
                org["department_id"],
                org["division_id"],
                1 if i % 3 else 2,
                "perf-synthetic",
                "2024-01-15",
                None,
                None,
                None,
                0,
                _NOW,
                _NOW,
            )
        )
    conn.executemany(
        "INSERT INTO employees ("
        " id, full_name, position_id, branch_id, department_id, division_id,"
        " employment_type_id, note, hire_date, contacts, home_address,"
        " social_insurance_number, is_archived, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )

    history_rows: list[tuple] = []
    hist_id = 1
    for i in range(1, employee_count + 1):
        if i % 4 == 0:
            continue
        status_id = (i % 6) + 1
        end_date = "2026-08-10" if status_id in (3, 4, 5, 6) else None
        history_rows.append(
            (hist_id, i, status_id, "2026-06-01", end_date, None, _NOW, account_id)
        )
        hist_id += 1
    conn.executemany(
        "INSERT INTO status_history ("
        " id, employee_id, status_id, start_date, end_date, note, created_at,"
        " created_by_account_id"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        history_rows,
    )
    conn.commit()
    return {"employee_count": employee_count, **org}


def _main() -> None:
    parser = argparse.ArgumentParser(description="Generate perf acceptance SQLite DB")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("perf-acceptance.db"),
        help="Output database path",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=_DEFAULT_COUNT,
        help="Number of synthetic employees (300–500 per TESTING §2.8)",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing file: {args.output}")
    if not 300 <= args.count <= 500:
        print(f"warning: count {args.count} outside recommended 300–500 range")

    from services.bootstrap import BootstrapService

    bootstrap = BootstrapService(clock=lambda: _NOW)
    conn, _session, recovery_code = bootstrap.initial_administrator_setup(
        db_path=args.output,
        login="perf-admin",
        password="PerfAdmin-1",
    )
    info = seed_perf_dataset(conn, employee_count=args.count, account_id=1)
    conn.close()
    print(f"created {args.output} with {info['employee_count']} employees")
    print("recovery code (save offline):", recovery_code)


if __name__ == "__main__":
    _main()
