# ADR-0008: Опциональные промежуточные уровни оргструктуры (департамент и отдел)

Статус: Принято
Дата: 2026-09-13
Автор: Claude (черновик по инициативе пользователя), принято пользователем 2026-09-13
Затронутый EPIC: EPIC-024

## Контекст

Текущая модель — жёсткая линейная цепочка (ТЗ §3.1: «Департамент —
Обязательно, привязан к филиалу»; «Отдел — Опционально, привязан к
департаменту»):

```
Филиал (обязателен)
└── Департамент (обязателен)
    └── Отдел (опционален)
```

Два независимых, но структурно одинаковых кейса не укладываются в неё:

1. Сотрудники уровня филиала (директор филиала, зам. директора, помощник
   руководителя) — для них нет департамента.
2. Отделы, обслуживающие руководство филиала напрямую (секретариат,
   делопроизводство) — не входят ни в какой департамент, но являются
   полноценными отделами со своими сотрудниками. У отделов сейчас физически
   нет `branch_id` — путь к филиалу есть только через `department_id`.

Оба случая — одна и та же архитектурная проблема: цепочка должна допускать
пропуск департамента на обоих уровнях, которые к нему примыкают.

Эта ADR фиксирует отклонение от ТЗ §3.1 в части обязательности поля
«Департамент» у сотрудника. Сам файл ТЗ не редактируется постфактум —
отклонение фиксируется здесь и записью в ROADMAP (EPIC-024).

## Рассмотренные варианты

**Для сотрудника без департамента:**

1. `department_id` опционален у `employees` и `divisions`. **Выбран.**
2. Служебный департамент «Руководство филиала» — отклонён (искусственная
   сущность, дублировалась бы для обоих кейсов отдельно).
3. Флаг уровня привязки — отклонён (дублирование источника истины).
4. Привязка через должность — отклонён (ломает фильтры/отчёты).

**Для отдела без департамента:**

A. Дать `divisions` собственный `branch_id` (симметрично `employees`),
   `department_id` опционален. **Выбран** — единообразная форма с
   сотрудником, не требует новой сущности.
B. Служебный департамент «Руководство филиала» — отклонён по той же причине.
C. «Виртуальный» департамент с `id = NULL` через представление/`COALESCE` —
   отклонён: усложняет каждый join и триггер ради экономии одного столбца.

**Выбор:** 1 + A.

## Решение

**Правила целостности:**

Для `employees`:

- `branch_id` — всегда обязателен.
- `department_id` — может быть `NULL`.
- `division_id` — может быть `NULL`. Если заполнен: `division.branch_id`
  должен совпадать с `employee.branch_id`, и `division.department_id`
  должен точно совпадать с `employee.department_id`, включая `NULL == NULL`.

Для `divisions`:

- `branch_id` — всегда обязателен (новое поле).
- `department_id` — может быть `NULL`.
- Если `department_id` заполнен — департамент должен принадлежать тому же
  `branch_id`, что и отдел.
- `UNIQUE(branch_id, name)` — имя отдела уникально в пределах филиала,
  независимо от департамента (нужно для однозначного сопоставления при
  импорте). Реальной БД с данными не существует — миграция не требует
  проверки существующих коллизий, ограничение действует со схемы вперёд.

**Схема — две последовательные миграции (table rebuild, SQLite не умеет
`ALTER COLUMN`):**

`0010_optional_department_for_divisions.sql`:

1. `PRAGMA foreign_keys = OFF`.
2. `divisions_new`: `branch_id INTEGER NOT NULL REFERENCES branches(id)`,
   `department_id INTEGER REFERENCES departments(id)` (без `NOT NULL`),
   `UNIQUE(branch_id, name)`, остальные столбцы без изменений.
3. Backfill:

```sql
INSERT INTO divisions_new
    (id, branch_id, department_id, name, is_archived, created_at, updated_at)
SELECT d.id, dep.branch_id, d.department_id, d.name, d.is_archived,
       d.created_at, d.updated_at
FROM divisions d JOIN departments dep ON dep.id = d.department_id;
```

4. `DROP TABLE divisions`, `RENAME`, пересоздать индекс
   `idx_divisions_department` + новый `idx_divisions_branch`.
5. Новые триггеры (по аналогии с 0004 для employees):

```sql
CREATE TRIGGER trg_divisions_org_consistency_insert
BEFORE INSERT ON divisions
BEGIN
    SELECT RAISE(ABORT, 'division department does not belong to branch')
    WHERE NEW.department_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM departments d
        WHERE d.id = NEW.department_id AND d.branch_id = NEW.branch_id
      );
END;
-- + зеркальный ..._update (BEFORE UPDATE OF branch_id, department_id)
```

6. Reparent-guard:

```sql
CREATE TRIGGER trg_divisions_no_rebranch_if_referenced
BEFORE UPDATE OF branch_id ON divisions
WHEN OLD.branch_id != NEW.branch_id
BEGIN
    SELECT RAISE(ABORT, 'cannot move division to another branch: referenced by employees')
    WHERE EXISTS (SELECT 1 FROM employees e WHERE e.division_id = OLD.id);
END;
```

7. `PRAGMA foreign_key_check`, затем `PRAGMA foreign_keys = ON`.

`0011_optional_department_for_employees.sql` — table rebuild
`employees.department_id` → nullable; исправленные триггеры 0004 с явной
проверкой `IS NOT NULL`; точное сравнение `division.department_id`
(включая `NULL`). Выполняется после 0010.

**Домен (`org_structure.py`):**

```python
@dataclass(frozen=True)
class DivisionRef:
    id: int
    branch_id: int
    department_id: int | None
```

`validate_org_assignment` — точное сравнение `department_id` (включая
`None`) вместо раздельных веток, плюс прямая сверка
`division.branch_id == assignment.branch_id`.

**Сервис (`services/directories.py`):** `create_division` — обязательный
`branch_id`, опциональный `department_id`, сервисная проверка
принадлежности департамента филиалу до триггера. `list_divisions` —
дополнительный фильтр `branch_id: int | None`.

**UI (`ui/directories_dialog.py`, вкладка «Отделы»):** выбор родителя —
конкретный департамент либо «— напрямую в филиале (без департамента)».

**UI карточки сотрудника:** список отделов включает и отделы департамента,
и отделы филиала без департамента; очистка департамента каскадно чистит
отдел.

**Импорт (`domain/employee_import.py`):**

- `ImportCatalog.divisions` → два словаря: `divisions_by_department:
  dict[tuple[int, str], int]` и `divisions_by_branch: dict[tuple[int, str], int]`.
- Пустая ячейка «Департамент» + непустая «Отдел» → искать в
  `divisions_by_branch`. Не найдено → ошибка строки.
- Непустая «Департамент» → поведение как раньше (`divisions_by_department`).
- Обе ячейки пусты → сотрудник без департамента и отдела — валидно.
- Непустое, но нераспознанное имя департамента/отдела — по-прежнему
  ошибка строки, не тихий `None` (защита от опечаток).

## Последствия

- Требуются две последовательные миграции (0010, 0011), обе — table
  rebuild, с тестами на копии непустой БД и `PRAGMA foreign_key_check`.
- ТЗ §3.1 в части «Департамент — Обязательно» — задокументированное
  отклонение через эту ADR, сам файл ТЗ не правится.
- Импорт: разделение каталога на два словаря — контролируемое расширение,
  не ломает обратную совместимость файлов, где обе ячейки заполнены.
- Явно НЕ вводится в этой ADR: третье состояние фильтра «показать только
  сотрудников/отделы без департамента» в roster/отчётах — отдельная
  задача при необходимости, не часть EPIC-024.

## Как проверяется

| Тест | Что проверяет |
|---|---|
| `test_adr0008_migration_divisions_backfill_branch_id_on_nonempty_db` | 0010: все отделы получают верный `branch_id` от своего департамента |
| `test_adr0008_division_name_unique_within_branch_regardless_of_department` | `UNIQUE(branch_id, name)` — второй отдел с тем же именем в филиале отклоняется |
| `test_adr0008_migration_employees_allows_null_department_on_nonempty_db` | 0011: данные не теряются, `foreign_key_check` чист |
| `test_adr0008_create_division_directly_under_branch` | Отдел без департамента создаётся, `department_id IS NULL`, `branch_id` верный |
| `test_adr0008_division_department_must_belong_to_branch_when_present` | Отдел с департаментом из другого филиала — запрещён |
| `test_adr0008_cannot_rebranch_division_referenced_by_employees` | Reparent-guard блокирует смену `branch_id` у отдела с сотрудниками |
| `test_adr0008_create_employee_branch_only` | Сотрудник филиала без департамента и отдела |
| `test_adr0008_create_employee_in_branch_direct_division` | Сотрудник без департамента, в отделе-секретариате |
| `test_adr0008_employee_department_must_exactly_match_division_department_including_null` | Несовпадение department между сотрудником и отделом — запрещено |
| `test_adr0008_import_empty_department_nonempty_division_matches_branch_division` | Импорт: пустой департамент + «Секретариат» → `divisions_by_branch` |
| `test_adr0008_import_empty_department_unknown_division_name_errors` | Импорт: несуществующее имя отдела → ошибка строки |
| `test_adr0008_import_both_department_and_division_empty_is_valid` | Импорт: директор филиала без департамента и отдела — валиден |

См. также `org_structure.py`, `0004_data_invariants.sql`,
`0005_org_reparent_guards.sql`, ТЗ §3.1.
