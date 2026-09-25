# ADR-0012: Сессии конвертации и снимки строк (EPIC-018)

Статус: Принято
Дата: 2026-09-25
Автор: Cursor (архитектурное предложение; принято человеком 2026-09-25)
Затронутый EPIC: EPIC-018
Связанные документы: `docs/ROADMAP.md` (EPIC-018), `ANCHOR_CORE.md`, `ANCHOR_PROTOCOL.md`,
`domain/employee_import.py` (`HEADER_TO_KEY`), ADR-0007 (граница transport),
ADR-0010 (identity/sync — без изменений)

## Контекст

EPIC-018 — офлайн desktop-приложение: построчный визард конвертации из XLSX/CSV
для заведения **новых** сотрудников из файлов с неполным набором **поддерживаемых**
колонок. Операционная модель: один аутентифицированный пользователь на одной
установке и одной базе `personnel.db`; параллельная работа разных пользователей
с одной БД не предполагается.

Требования `docs/ROADMAP.md` (EPIC-018): гибкие колонки (`HEADER_TO_KEY`),
обязательно только ФИО в файле для постановки строки в очередь, черновик
карточки, явные Save/Skip, предупреждение о дубле ФИО без автосвязывания,
таблица `import_sessions`, продолжение по хешу содержимого файла, автоочистка
сессий через 30 дней неактивности.

ADR-0006 **отменена**; её дополнение v2 о снимках строк — **не** является
принятой архитектурой. ADR-0010 не описывает `import_sessions`. EPIC-009
(batch-импорт со строгими обязательными колонками) **не меняется**.

## Проблема

Нужно временное хранение pending-строк в SQLCipher для resume **в рамках одной
аутентифицированной сессии приложения**, атомарность Save/Skip, минимальный
объём ПДн и отделение от transport/reconcile — без полей учётной записи в
staging-таблицах и без over-engineering под теоретический concurrent multi-user
сценарий на одной БД.

## Рассмотренные варианты

1. **Хранить только путь к файлу.** Отклонено: resume в активной auth-сессии
   требует данных строк при недоступности повторного ingest; путь не заменяет
   снимок mapped-значений.
2. **Хранить полный файл в БД.** Отклонено: избыточные ПДн и дублирование.
3. **`started_by_account_id` / `last_login_account_id` в схеме или settings.**
   Отклонено: операционная модель — один пользователь на установку; политика L2
   (purge на каждый login) закрывает границу авторизации без ownership в staging.
4. **Сохранять conversion staging через crash/restart.** Отклонено: требование
   — resume пока активна авторизация приложения; после login staging намеренно
   сбрасывается.
5. **Amend ADR-0010.** Отклонено: смешение directory/sync identity с локальным
   визардом конвертации.

## Решение

### Операционная модель и граница авторизации

Сессии конвертации — **временное состояние приложения под активной
авторизацией**, а не долгоживущие пользовательские данные.

**Политика жизненного цикла L2 (принято):** выполняется

```sql
DELETE FROM import_sessions;
```

(строки `import_session_rows` удаляются `ON DELETE CASCADE`)

при:

- **каждой** успешной аутентификации (`login`);
- **явном** `logout`;
- **успешной смене пользователя** (teardown предыдущей аутентифицированной
  сессии).

**Порядок:** после успешной аутентификации и **до** того, как flow конвертации
может возобновить staging, выполняется purge L2. Пользователь не может продолжить
pending-конвертацию через границу авторизации.

**Намеренно отсутствуют:**

- `started_by_account_id` и любая привязка владельца в `import_sessions`;
- `last_login_account_id` и иные механизмы сохранения staging через границу
  авторизации;
- реестр завершённых сессий (completed-session history);
- replay-protection / запрет повторного импорта того же файла.

**Семантика по сценариям:**

| Сценарий | Поведение |
|----------|-----------|
| **Та же аутентифицированная сессия приложения** | Выбор файла → хеш → при наличии `import_sessions` с этим хешом и pending-строк — **resume без повторного ingest**; прерывание UI не должно само по себе уничтожать pending (пока не сработал logout/login/switch/purge L2). |
| **Новая граница авторизации** (login / logout / switch) | Полный purge staging; предыдущая конвертация **недоступна**. |
| **Краш / принудительное завершение процесса** | Сохранение conversion staging **не требуется**; строки могут физически остаться в БД до **следующего успешного login**, где L2 их удалит. Это **намеренно**, не дефект. Crash-recovery semantics **не** вводятся. |

Требование **не** формулируется как «конвертация переживает перезапуск
приложения». Требование **формулируется** как: пока авторизация активна,
пользователь может возобновить прерванную конвертацию по pending-строкам после
повторного выбора **того же** файла (тот же хеш содержимого).

### Формат источника и ingest

- Первая строка файла — заголовки.
- Учитываются только заголовки, распознанные `HEADER_TO_KEY` (`map_headers` /
  `header_key`).
- Нераспознанные колонки **отбрасываются**.
- В `values_json` попадают **только** mapped internal keys → строковые значения
  ячеек после `cell_text`.
- Сырой документ, произвольные колонки, `headers_json` **не** хранятся.

**ФИО:** строка попадает в очередь только при непустом `full_name` после разбора.
Строки без ФИО **не** создают `import_session_rows` и **не** показываются в
визарде (допустима сводка при ingest в UI).

### Resume (нормативная формулировка)

Нормативная формулировка:

> resume without re-ingest after identifying the session by the selected file's
> content hash.

(В продуктовой документации на русском: возобновление **без повторного ingest**
после обнаружения сессии по хешу **выбранного** файла.)

**Поток:**

1. Пользователь запускает конвертацию.
2. Пользователь **выбирает исходный файл** (файл нужен, чтобы вычислить хеш).
3. `file_content_hash = SHA-256(raw_file_bytes).hexdigest()` (`hashlib`, как в
   репозитории для checksum миграций).
4. Если существует `import_sessions` с этим `file_content_hash` и есть
   pending-строки:
   - **resume**;
   - обновить `last_accessed_at` (открытие/возобновление сессии);
   - **не** выполнять ingest повторно.
5. Иначе: ingest → создание pending-строк и новой сессии.
6. Визард читает только `import_session_rows.values_json`, порядок
   `ORDER BY source_row_number`.
7. После шага 4 исходный файл для **очереди pending** не обязателен.

**Не использовать** формулировку «resume без исходного файла». Холодный resume
без выбора файла (без вычисления хеша) — **вне скоупа** EPIC-018.

Повторный выбор файла с тем же содержимым **после** purge L2 или после
завершения конвертации (сессия удалена): новый ingest, новая сессия;
предупреждения о дублях сотрудников; решение за пользователем.

### Схема БД (минимальная)

```text
import_sessions
    id INTEGER PRIMARY KEY
    file_content_hash TEXT NOT NULL UNIQUE
    last_accessed_at TEXT NOT NULL

import_session_rows
    id INTEGER PRIMARY KEY
    session_id INTEGER NOT NULL REFERENCES import_sessions(id) ON DELETE CASCADE
    source_row_number INTEGER NOT NULL
    values_json TEXT NOT NULL

UNIQUE (session_id, source_row_number)
INDEX (last_accessed_at)
```

`source_filename` — только опциональные UX-метаданные; **в минимальной схеме не
включается**, пока нет явного требования UI.

**Не вводить:** `started_by_account_id`, `last_login_account_id`, `headers_json`,
`sort_order`, `created_at`, completed-session registry, replay registry.

### `last_accessed_at`

Обновляется **только** при:

1. открытии/возобновлении существующей сессии конвертации;
2. успешном Save строки;
3. успешном Skip строки.

**Не** обновляется при: next/previous navigation, редактировании полей,
отрисовке UI, показе предупреждения о дубле.

Цель: измерять значимую активность сессии без продления retention из-за
пассивной навигации по UI.

### Retention и PII

Модель:

```text
source file → mapped pending rows → human Save/Skip → row deleted
→ session deleted when no pending rows remain
```

- Обработанные снимки не хранятся (строка удаляется при успешном Save/Skip).
- Сессия удаляется, когда pending-строк не осталось.
- **Lazy cleanup:** при входе в flow конвертации удалить сессии, у которых
  `last_accessed_at` старше 30 суток.
- Purge L2 на login/logout/switch удаляет весь оставшийся conversion staging.
- ПДн только в `values_json` внутри SQLCipher; **не** логировать содержимое
  снимков, ФИО, адреса, СНИЛС в журналах действий и сообщениях об ошибках.

### Транзакции

Оркестратор конвертации владеет одной транзакцией на `Connection` (по образцу
`TransportImportApplyService`). Вторая независимая реализация создания сотрудника
**запрещена**; допускается узкий шов `commit=False` на существующем пути
`EmployeeService` с теми же validation и `employee.create` audit.

**Save:**

```text
BEGIN
  validate employee input
  create employee through existing EmployeeService path with commit=False
  write employee.create audit (как при обычном create)
  DELETE current import_session_row
  UPDATE import_sessions.last_accessed_at
  DELETE import_sessions IF no pending rows remain
COMMIT
```

При ошибке: `ROLLBACK`; pending-строка **остаётся**.

**Skip:**

```text
BEGIN
  DELETE current import_session_row
  UPDATE import_sessions.last_accessed_at
  DELETE import_sessions IF no pending rows remain
COMMIT
```

Сотрудник **не** создаётся; audit `employee.create` **не** пишется.

### Дубли сотрудников

Без изменения правил EPIC-018: совпадение ФИО (логика в духе
`EmployeeImportService._duplicate_warnings` где применимо) → предупреждение;
справочный read-only просмотр существующей карточки; **нет** автосвязывания;
пользователь может явно сохранить новую карточку при успешной валидации.

### Права

`Permission.IMPORT_EXPORT` и `Permission.MANAGE_EMPLOYEES`, разблокированная
сессия БД (`SessionState.require_unlocked()`) — как у `EmployeeImportService`.

### EPIC-021 (граница интеграции)

EPIC-018 предоставляет стабильный entry point приложения:

```text
run_conversion_wizard_flow(parent, services, ...)
```

Будущий `DatabaseOperationsDialog` (EPIC-021) вызывает этот flow с вкладки
«Конвертация данных». Shell, вкладки, видимость по ролям, перенос бэкапа —
**EPIC-021**, не данный ADR.

### Явные non-goals

- Семантика EPIC-009 (batch-импорт);
- Transport / EPIC-020;
- Reconcile «Сверка с базой»;
- Обновление существующих карточек через визард;
- Concurrent multi-user staging на одной БД;
- Crash-recovery beyond L2 purge на следующем login;
- Cold resume без file picker;
- Фоновый scheduler для очистки;
- `account_id` в staging;
- Completed-session / replay registries.

## Последствия

- Требуется миграция схемы БД (`import_sessions`, `import_session_rows`) с
  тестом на непустой БД (`ANCHOR_PROTOCOL.md` §6, `TESTING.md`).
- Реализация purge L2 в `AuthenticationService.login`, `logout` и teardown при
  switch-user **до** любого resume в flow конвертации.
- Новый сервис конвертации, repository, UI-визард, тесты по таблице ниже.
- Ссылку в `docs/ROADMAP.md` на дополнение ADR-0006 целесообразно заменить на
  ADR-0012 отдельным docs-изменением.

Затрагивает: `ANCHOR_CORE.md` §4 (audit при Save в той же транзакции, что
создание сотрудника); не меняет матрицу ролей ТЗ §4.1.

## Как проверяется

| Тест | Что проверяет |
|------|----------------|
| `test_adr0012_resume_without_reingest_same_auth_session` | Тот же auth session, тот же файл/хеш, очередь из БД без повторного ingest |
| `test_adr0012_new_ingest_when_no_session` | После purge L2 или первый запуск в auth session |
| `test_adr0012_login_purges_all_import_sessions` | Политика L2 на login |
| `test_adr0012_logout_and_switch_purge_sessions` | Purge на logout и switch-user teardown |
| `test_adr0012_fio_less_rows_not_queued` | Пустое ФИО → нет `import_session_rows` |
| `test_adr0012_save_atomic_employee_and_row` | Save: commit целиком; rollback оставляет pending row |
| `test_adr0012_skip_no_employee` | Skip без create и без employee audit |
| `test_adr0012_lazy_cleanup_30_days` | Удаление по `last_accessed_at` |
| `test_adr0012_migration_on_nonempty_db` | Миграция применяется на непустой БД |

См. также DoD EPIC-018 в `docs/ROADMAP.md` (визард save/skip/дубль, resume по
хешу в рамках auth session, автоочистка).
