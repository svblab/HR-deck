# ADR-0007 Addendum — Долговечность исходящего экспорта (outbound export durability)

Статус: Принято  
Дата: 2026-09-30  
Автор: Johan (утверждает); черновик подготовлен с помощью Cursor  
Затронутый EPIC: EPIC-021 (операторский UI обмена); затрагивает контракт EPIC-020 export  
Relates to: ADR-0007, ADR-0010

## Контекст

ADR-0007 задаёт монотонную позицию транспорта `(generation, sequence)`,
цепочку `WK` и атомарность **приёма** пакета (transport-state продвигается
только вместе с успешным apply). Для **исходящего** экспорта в текущей
реализации (включая операторский путь EPIC-021) зафиксирован иной порядок:
состояние отправителя продвигается **до** успешной выдачи файла `.hrpkg`.

Факты (верификация по коду / F1):

1. **Коммит до сохранения файла.** Оркестратор сначала вызывает
   `TransportExportAdminService.export_package` (крипто, запись
   `transport_package_records` со статусом `PENDING`, продвижение
   `accepted_sequence` / `current_wk_id`, audit) и делает `commit()`, затем
   (опционально) `DirectorySyncService.record_export` с отдельным `commit()`,
   и только после этого UI показывает диалог сохранения / пишет байты на диск.
   Отмена диалога или ошибка записи оставляют БД уже продвинутой; отката нет.
2. **Двойной commit.** Транспортный state и watermark’и
   (`sync_watermarks`) коммитятся **раздельно** двумя вызовами `commit()`.
3. **`PENDING` не переходит дальше.** Исходящая запись журнала создаётся с
   `classification = PENDING`. Нет кода, который обновляет исходящий `PENDING`
   в `accepted` / `rejected` / `replay_observed`. Канал peer ACK **не
   реализован**. Значение `REPLAY_OBSERVED` есть в схеме/enum, но **нигде не
   записывается**.
4. **STALE на N+1.** При потере пакета N повторный экспорт получает
   sequence N+1 (монотонность `record_outbound_export`). Получатель, ожидающий
   contiguous next sequence, отклоняет N+1 как stale, если N не был принят.
5. **Перекос watermark’ов.** Если `record_export` уже закоммитил
   `last_exported_at`, а файл не доставлен, последующие инкрементальные
   сборки могут **не включить** строки, которые peer так и не получил.
6. **Нет force-full export / сброса watermark’ов** в продуктовом API.
   Отсутствие строки watermark фактически даёт полный дамп таблицы; явного
   операторского «полный экспорт» нет.
7. **`reinit_direction` не сбрасывает watermark’и.** Reinit поднимает
   `generation`, обнуляет `accepted_sequence` / `current_wk_id` и ставит
   `reinit_required`; строки `sync_watermarks` и исторические
   `transport_package_records` **сохраняются**. После сбоя экспорта + reinit
   перекос watermark’ов может остаться.

Нужно зафиксировать: когда исходящий transport-state и watermark’и **могут**
продвигаться относительно долговечной выдачи пакета на диск, и какова
семантика `PENDING` на стороне отправителя.

## Рассмотренные варианты

### A — Sink + один commit после успешной записи файла

Диалог выбора пути — **до** транзакции. В одной транзакции: построение /
запись transport-state + audit + `record_export` (без внутренних commit),
затем запись файла на диск, затем единый `COMMIT`. При ошибке sink /
отмене до старта транзакции — БД не меняется.

| | |
|---|---|
| **Плюсы** | «Не продвинули state без попытки выдачи»; один commit; watermark и transport согласованы; соответствует духу атомарности ADR-0007 на стороне приёма и правилу «No UI in transaction». |
| **Минусы** | Если порядок «записать финальный файл → COMMIT», остаётся crash-окно: файл уже может быть доставлен/принят peer’ом, а отправитель после сбоя откатится и позже переиздаст **тот же** sequence с **другим** `package_id` — разрыв цепочки WK / freshness (см. Решение). Рефакторинг фасадов и e2e. |

### A′ — Sink + один commit, порядок: `*.<package_id>.tmp` + fsync → COMMIT → `os.replace` в финальное имя

То же, что A, но порядок I/O и имена файлов жёстко зафиксированы так, чтобы
остаток после rollback **отличался** от остатка после успешного COMMIT:

```text
(диалог пути — вне транзакции; final = выбранный .hrpkg; target_path известен)
assert not conn.in_transaction
BEGIN IMMEDIATE
  TransportExport…(commit=False)         # package_id уже известен
  DirectorySyncService.record_export…(commit=False)
  write(final.<package_id>.tmp) + fsync   # недоверенный temp, не «выдан»
  fsync родительского каталога            # обязательно (Linux); OSError — игнорировать
COMMIT
os.replace(final.<package_id>.tmp → final)  # один шаг; без промежуточного .partial
fsync родительского каталога            # обязательно (Linux); OSError — игнорировать
```

После записи и fsync данных `*.tmp`, а также после `os.replace`,
**обязательно** выполняется `fsync` родительского каталога (целевая
платформа — Debian/Linux). `OSError` от fsync каталога (файловая система
без поддержки) **игнорируется**. Без fsync каталога данные файла могут
быть durable, а запись в каталоге — потеряна при сбое питания.

| | |
|---|---|
| **Плюсы** | Инвариант: «если БД продвинулась — байты пакета durably на диске (финальный `.hrpkg` или `*.<package_id>.tmp`, чей `package_id` есть в `PENDING`)». Crash-окно plain A закрыто. Orphan после rollback (`*.tmp` с неизвестным `package_id`) отсекается проверкой против БД. |
| **Минусы** | Дисциплина оркестратора и тесты crash/replace; краткая write-транзакция на время fsync; операторская процедура для orphan `*.tmp` после COMMIT (см. ниже). |

### B — Persist `wire_bytes` для re-emission

Хранить сериализованный пакет (BLOB) вместе с `PENDING`, дать API/UI
повторной выдачи того же `package_id` / sequence без reinit.

| | |
|---|---|
| **Плюсы** | Восстановление потерянного файла без разрыва generation; не требует координации peer reinit. |
| **Минусы** | Размер БД/бэкапов; retention/TTL; политика безопасности ciphertext at rest; новый API/UI; **по-прежнему нет peer ACK**; правила exact-replay vs повторной выдачи. Не устраняет сам порядок «commit до выдачи», если не комбинировать с A/A′. |

### C — Status quo + recovery через `reinit_direction`

Оставить commit-before-file; при потере пакета — согласованный reinit.

| | |
|---|---|
| **Плюсы** | Нет рефакторинга фасадов; протокол generation уже описан addendum’ом epoch. |
| **Минусы** | Операционно тяжело; UI reinit может отсутствовать; **watermark’и не сбрасываются**; внутри generation gap остаётся; `PENDING` остаётся «мёртвым» журналом; cancel/ошибка записи продолжают продвигать state. |

## Решение

**Предлагается вариант A′.**

### Инвариант

> Если БД отправителя продвинула исходящий transport-state (и связанные
> watermark’и) для пакета с данным `package_id`, то байты этого пакета
> **долговечно** присутствуют на диске — либо как финальный `.hrpkg`, либо
> как `*.<package_id>.tmp` после успешного `COMMIT` (до `os.replace`).
> Файл `*.tmp`, чей `package_id` **не** найден в
> `transport_package_records` отправителя со статусом `PENDING`, **не**
> считается выданным и подлежит удалению.

### Почему не простой A («write → commit» с rename до commit)

Порядок «записать под финальным именем (или rename до COMMIT) → COMMIT»
оставляет окно после успешной записи файла и **до** COMMIT:

1. Процесс падает / откатывает транзакцию → у отправителя sequence/WK
   **не** продвинуты.
2. Файл уже мог быть скопирован оператором и **принят** получателем
   (inbound accept продвигает peer state и устанавливает следующий ожидаемый
   sequence / WK).
3. Повторный экспорт на отправителе снова выдаёт sequence N, но с новым
   `package_id` и новой веткой WK → для peer это либо stale/conflict, либо
   принятие пакета, **несовместимого** с уже установленной цепочкой WK от
   первого файла.

Таким образом plain A может **разойти** цепочку WK между установками, хотя
«файл вроде был выдан».

### Почему A′ снимает это окно

1. **До COMMIT** на диске только
   `<final>.<package_id>.tmp`. Это имя **недоверенное**: операторский
   контракт **никогда** не считает `*.tmp` выданным пакетом (его нельзя
   отдавать peer’у как `.hrpkg`).
2. **После успешного COMMIT** — ровно один `os.replace(tmp → final)`.
   Промежуточного `.partial` **нет**. Если replace успел — выдан финальный
   файл; если нет — остаётся `*.tmp`, но DB уже содержит `PENDING` с тем же
   `package_id`, поэтому остаток отличим от мусора после rollback.
3. **Различение orphan’ов:**
   - rollback / crash до COMMIT → `*.tmp` с `package_id`, которого **нет**
     в `transport_package_records` (или нет как `PENDING`) → удалить;
   - COMMIT успешен, `os.replace` не успел → `*.tmp` с `package_id`,
     который **есть** как `PENDING` → файл **issued** этой БД (см.
     смысл проверки ниже); оператор/UI делает retry на **том же**
     `target_path` или relocate на новый путь (правила ниже), **не**
     переиздавая новый sequence.
4. **Retry на том же пути / relocate после COMMIT.** Байты — из in-memory
   `wire_bytes`, иначе из существующего `*.tmp` после сверки
   `package_id`/cleartext header со строкой `PENDING`.
   - Retry на **том же** `target_path`: `os.replace(old.tmp → final)`.
   - **Relocate** (оператор выбрал другой final path): **запрещено**
     переносить старый `*.tmp` через `os.replace` на другой том/путь
     (`os.replace` между разными файловыми системами падает с EXDEV
     (errno 18), проверено на debian:12). Нужно: записать байты заново в
     свежий `<new_final>.<package_id>.tmp` рядом с новым target → fsync
     данных + fsync каталога (обязательно на Linux; OSError — игнорировать)
     → `os.replace` в
     `new_final`; **старый** `*.tmp` удалять **только** после
     подтверждённого успеха; при abandon — оставить старый `*.tmp` и
     показать оператору его полный путь.
5. `package_id` известен до записи temp (`TransportExportService` генерирует
   его до возврата `wire_bytes`) и читается из cleartext routing header
   wire-пакета без расшифровки; плюс он зашит в имя файла — проверка
   «файл ↔ БД» не требует crypto.

### Семантика `PENDING`

На стороне отправителя `PENDING` — **терминальная** запись журнала:
«пакет выпущен и durably записан» (по инварианту A′). Это **не** фаза
ожидания подтверждения доставки:

- **«выпущен и durably записан» ≠ «доставлен peer’у».** Потеря носителя
  после успешного сохранения финального файла — **вне рамок** этого
  addendum; закрывается только отдельным companion-заданием force-full
  export / сброса watermark’ов (см. открытый вопрос №2).
- канала peer ACK нет и в объём этого addendum **не** вводится;
- жизненных переходов `PENDING → …` нет (строка **никогда** не уходит
  из `PENDING`);
- `REPLAY_OBSERVED` остаётся зарезервированным и **неиспользуемым**
  (как сейчас в коде).

**Смысл проверки `PENDING`:** наличие строки доказывает лишь
«пакет **выпущен этой** БД отправителя» (**issued**), **не**
«недоставлен» / «ещё не принят peer’ом». Решение «отправлять ли файл»
принимает оператор по audit-логу и состоянию peer’а. Если peer уже принял
тот же `package_id`, повторная доставка безвредна (inbound классифицирует
как replay / idempotent success).

Приём и классификация на получателе не меняются (ADR-0007 /
generation addendum).

### Композиция транзакции

- **Владелец** единственной транзакции — caller/orchestrator (UI-сервис
  экспорта или аналог), не доменные фасады.
- Обратно совместимый подход к фасадам: параметр
  `commit: bool = True` у `TransportExportAdminService.export_package` и
  `DirectorySyncService.record_export` (default сохраняет текущее поведение
  с внутренним commit; оркестратор A′ передаёт `commit=False`).
  Низкоуровневый `TransportExportService` уже не коммитит — это сохранить.
- Оркестратор **обязан** перед `BEGIN IMMEDIATE` проверить
  `not conn.in_transaction` и при нарушении **завершиться с явной ошибкой**
  (не пытаться вложить IMMEDIATE в уже открытую implicit txn).
- **UI внутри транзакции запрещён** (ADR-0007 «No UI in transaction»):
  диалог выбора пути и подтверждения — **до** `BEGIN`; выбранный
  `target_path` (финальный `.hrpkg`) к этому моменту уже известен и
  пишется в audit `details` как JSON-quoted значение (см. формат выше).
- Критическая секция короткая: assert чистого соединения →
  `BEGIN IMMEDIATE` → мутации БД → запись
  `<final>.<package_id>.tmp` + fsync данных + fsync каталога (обязательно
  на Linux; OSError — игнорировать) → `COMMIT` → `os.replace` + fsync
  каталога (обязательно на Linux; OSError — игнорировать). Без модальных
  диалогов и без сети.
- При ошибке COMMIT (или любом откате до COMMIT): удалить соответствующий
  `*.tmp`, если он создан; state не продвинут; in-memory
  `TransportExportResult` / `wire_bytes` оркестратор **обязан отбросить**.

### Формат audit `details` для `transport.package.export`

Поле `user_action_log.details` — свободный `TEXT` (схема без изменений).
Для записи экспорта сохраняется стиль `key=value`, разделённый пробелами,
как сейчас (`package_id=… generation=… …`). Значения, которые **могут
содержать пробелы** (в частности `target_path`), пишутся как
**JSON-quoted** строка через `json.dumps` (двойные кавычки и экранирование),
например: `target_path="/mnt/share/out dir/pkg.hrpkg"`. Остальные поля без
пробелов допускается оставлять без кавычек.

`details` этой записи предназначены для **человеческого** чтения в UI
журнала и для поиска по подстроке / `LIKE` (в т.ч. по `package_id=…`).
Машинного парсера `key=value` в `src/` / `tests/` **нет** (только
substring-assert’ы в тестах и отображение/`export_cells` целиком) — на
структурный разбор опираться нельзя, пока такой парсер не введён явно.
Поле `details` показывается в UI журнала действий и попадает в выгрузки
журнала, поэтому `target_path` (локальный путь, который может содержать
имя пользователя) там **виден**.

Диалог пути выполняется **до** BEGIN, поэтому `target_path` известен к
моменту записи audit внутри транзакции.

### Правило orphan `*.tmp` и процедура оператора («проверить файл по БД»)

Автоматического recovery **нет**.

Минимальная ручная процедура:

1. Найти запись `user_action_log` с `action_type = transport.package.export`
   и нужным `package_id` (LIKE / UI); из `details` взять JSON-quoted
   `target_path` (ожидаемый финальный `.hrpkg`) и рядом искать
   `<final>.<package_id>.tmp`.
2. Извлечь `package_id` из имени файла; при сомнении — разобрать cleartext
   routing header wire-байтов (`deserialize_transport_package` /
   `parse_routing_metadata_bytes`, без decrypt).
3. В БД отправителя:
   `SELECT … FROM transport_package_records WHERE package_id = ? AND classification = 'pending'`.
4. **Строка есть** → файл **issued** этой БД (не «undelivered»); байты —
   из in-memory `wire_bytes` иначе из `*.tmp`; сверить header/`package_id`
   с `PENDING`; затем retry `os.replace` на исходный `target_path` **или**
   relocate: записать новый `<new_final>.<package_id>.tmp` → fsync →
   `os.replace` → удалить старый `*.tmp` только после успеха; при abandon
   оставить старый `*.tmp` и показать полный путь. **Не** двигать старый
   `*.tmp` на другой том через `os.replace`.
5. **Строки нет** → файл от rollback/сбоя до COMMIT; **удалить**, не
   выдавать peer’у.

### Влияние на ADR-0010

Продвижение `sync_watermarks.last_exported_at` допускается **только в том
же COMMIT**, что и исходящий transport-state данного пакета. Отдельный
второй commit watermark’ов после транспортного — **запрещён** для этого
пути. Инкрементальность «после успешной отправки» в ADR-0010 читается как
«после успешного durable export» в смысле инварианта A′.

## Последствия

- Проще: cancel / ошибка до COMMIT не двигают sequence/WK/watermark;
  нет dual-commit skew между транспортом и directory sync; операторский
  контракт совпадает с «пакет выдан durably» (не «доставлен»).
- Сложнее: рефакторинг admin/record_export под `commit: bool = True`;
  тесты crash/replace/orphan-check; короткий write-lock на время fsync;
  обязательный fsync родительского каталога на Linux после tmp и после
  `os.replace` (с игнорированием `OSError` на неподдерживающих ФС);
  UI/runbook для `os.replace` failure и процедуры «проверить файл по БД»
  через audit `target_path`.
- На debian:12 (Python 3.11) `os.replace` поверх destination, открытого
  другим процессом, **успешен** (конфликта file-lock нет) — отдельный
  failure mode «заблокированный destination» обрабатывать не нужно.
- Миграция схемы БД **не** требуется для A′ (поле `details TEXT` уже есть;
  BLOB/`wire_bytes` — только если позже выбрать B).
- Контракты: обновить ссылки в EPIC-021 / runbook при реализации; при
  необходимости уточнить формулировку ADR-0010 «после успешной отправки».
- Промежуточная схема temp-файлов PR #132 (уникальное `*.partial` до
  экспорта, потому что `package_id` ещё неизвестен) — **временный
  stopgap** и при реализации A′ **заменяется** схемой
  `<final>.<package_id>.tmp` → `os.replace` этого addendum.
- **Restore из backup (вне рамок этого ADR):** `BackupService.restore_backup`
  / откат `UpgradeService` атомарно подменяют файл БД (+ keywrap) и
  открывают новое соединение; **нет** предупреждения про transport и
  **нет** сброса/`reinit` transport-state или watermark’ов. Если
  отправителя откатили на состояние **до** экспорта, чей файл уже
  доставлен peer’у, строка `PENDING` исчезает, а тот же sequence может
  быть выдан снова с **другой** цепочкой WK. Лечение — согласованный
  `reinit_direction`; предупреждение в UI restore — кандидат на
  follow-up, не часть этого addendum.

### План реализации: in-memory state и rollback (верификация кода)

Перед кодированием A′ проверить/зафиксировать, что rollback БД не
оставляет «живой» логики на объектах сервисов:

- `TransportKeyStore` / `TransportStoreRepository` (+ chain/identities):
  на экземпляре только `_conn` / `_clock` / `_repo` — **кэшей** WK,
  sequence, direction **нет**; все чтения идут из БД
  (`src/services/transport_keys.py`, `src/data/transport_store*.py`).
- `TransportExportService` / `TransportExportAdminService`: нет полей
  last-known WK/sequence; результат — возвращаемый
  `TransportExportResult` (`wire_bytes`, `package_id`, `generation`,
  `sequence`, `package`) у **caller’а**. После `rollback` оркестратор
  **обязан отбросить** этот объект и не писать его на диск.
- `DirectorySyncService`: репозитории + session; watermark’и читаются
  заново в `build_export_package` / пишутся только в `record_export` —
  **нет** межкаллового кэша watermark’ов
  (`src/services/directory_sync.py`).
- Эфемерные локали экспорта (`sk_material`, `WkKeyRecord`, routing) живут
  только в стеке вызова и сами не переживают rollback на `self`.

Итого: сервисных кэшей, которые `conn.rollback()` не откатит, **не
найдено**; риск — удержание `TransportExportResult` / `wire_bytes` у
оркестратора после rollback (инвалидировать явно).

- **`conn.in_transaction`:** у `sqlcipher3.dbapi2.Connection` (зависимость
  проекта `sqlcipher3>=0.6,<1`; проверено на установленном `0.6.x` /
  API-совместимо с `sqlite3`) атрибут **`in_transaction` есть** и отражает
  открытую txn. В `src/` / `tests/` вызовов `in_transaction` **не найдено**
  — оркестратор A′ должен начать ими пользоваться: `assert not
  conn.in_transaction` перед `BEGIN IMMEDIATE`. Альтернатива не нужна,
  пока используется этот драйвер.

### Модель соединений и фоновых писателей (верификация кода)

Проверено по `src/` перед записью этого addendum:

- **Фоновых потоков, пишущих в ту же БД, нет:** в приложении не используются
  `threading` / `QThread` / thread-pool / `multiprocessing` для записи в
  `personnel.db`. Таймеры UI (`QTimer` в `MainWindow`) не открывают второе
  соединение и не пишут в БД в фоне.
- **Обычная сессия — одно соединение:** `MainWindow` держит единый
  `self._conn`, сервисы разделяют его.
- **Вторые соединения бывают эпизодически**, не как параллельные writers
  экспорта: unlock/login (`AuthenticationService` → `connect`),
  restore/upgrade (`BackupService` / `UpgradeService` → временный `connect`
  с последующей заменой `_conn`). Параллельное открытие второго соединения
  при уже открытом main window покрыто тестами, но это путь смены сессии,
  не фоновый writer.
- **`busy_timeout` в `data/db.py` не выставляется** (только
  `foreign_keys=ON` и pragmas SQLCipher). При `BEGIN IMMEDIATE` на время
  короткой критической секции A′ конкурирующее второе соединение получит
  `SQLITE_BUSY` без ожидания, пока timeout не задан. Для текущего
  single-writer UI-модели это приемлемо при коротком fsync; если позже
  появятся параллельные writers — потребуется явный `busy_timeout` и/или
  сериализация на уровне приложения (см. ADR-0007 concurrent direction
  writer).

### `BEGIN IMMEDIATE` и `isolation_level` (верификация кода)

- Соединение из `data/db.connect` / `create_database` **не** меняет
  `isolation_level`; у `sqlcipher3`/`sqlite3` по умолчанию это legacy
  `''` (не `None`): DML неявно открывает deferred-транзакцию до
  `commit()`/`rollback()`.
- Явный `BEGIN IMMEDIATE` **безопасен только если** на соединении **нет**
  уже открытой транзакции (`in_transaction is False`). Иначе SQLite:
  `OperationalError: cannot start a transaction within a transaction`.
- Существующие сервисы избегают «висящей» implicit txn тем, что каждая
  фасадная операция заканчивается `commit()` или `rollback()`
  (`TransportExportAdminService`, `DirectorySyncService.record_export`,
  import apply и т.д.). Оркестратор A′ обязан стартовать с чистого
  соединения (после предыдущего commit/rollback) либо явно проверить
  отсутствие открытой txn перед `BEGIN IMMEDIATE`.
- Единственный явный `BEGIN` в `src/` — `data/migrations.py` (ставит
  `isolation_level = None`, затем `BEGIN` / `COMMIT` / `ROLLBACK`).
  **`BEGIN IMMEDIATE` в `src/` и `tests/` не найден** (упоминается только
  в ADR-0007 как implementation model).

## Открытые вопросы

1. **Аудит неуспешных/отменённых попыток** после rollback (до COMMIT).
   **Предлагаемое разрешение:** при cancel — **без** audit-записи; при
   failure — audit в **отдельной короткой транзакции после rollback**
   (точная формулировка action/result — на усмотрение maintainer’а).
2. **Force-full export / сброс watermark’ов** — отдельный companion-issue;
   этот addendum не вводит API полного экспорта и не меняет
   `reinit_direction` wrt `sync_watermarks`. Обязателен как парная задача
   к потере носителя после успешного save (см. семантику `PENDING`).
3. **Связка preview ↔ export** (сейчас независимые `build_export_package`) —
   отдельная задача; не блокирует принятие A′.
4. **Orphan `*.tmp` после COMMIT до `os.replace` / relocate.**
   **Предлагаемое разрешение:** процедура «проверить файл по БД» с
   поиском через audit `target_path` (JSON-quoted в `details`); **без**
   автоматического recovery. UI предлагает retry на том же пути или
   relocate через **новый** `*.tmp` (не move старого между томами); при
   abandon оставлять старый `*.tmp` с полным путём на экране. Проверка
   `PENDING` = issued, не undelivered.

## Как проверяется

Минимальный контракт тестов при реализации A′:

| Сценарий | Ожидание |
|---|---|
| Cancel диалога до BEGIN | БД не изменена (sequence/WK/watermark/PENDING) |
| Ошибка sink (ENOSPC и т.п.) до COMMIT | ROLLBACK; `*.tmp` удалён (если успели создать); state не продвинут |
| Ошибка COMMIT | `*.tmp` удалён; нет финального файла; state не продвинут |
| Crash после COMMIT до `os.replace` | Есть `<final>.<package_id>.tmp`; state продвинут (`PENDING`); check-file против БД ⇒ issued; retry/`os.replace` без нового sequence |
| Rollback затем crash | `*.tmp` с `package_id`, отсутствующим в `PENDING`, check-file **не** принимает; файл удаляется / не выдаётся |
| Ошибка `os.replace` после COMMIT | `*.tmp` остаётся; БД продвинута; UI сообщает и предлагает retry/save-as из in-memory `wire_bytes` иначе из `*.tmp` после сверки header/`package_id` с `PENDING` |
| Relocate после failed replace | Новый `<new_final>.<package_id>.tmp` + fsync + `os.replace`; старый `*.tmp` удалён только после успеха; при abandon старый `*.tmp` сохранён и путь показан; cross-volume move старого tmp **не** используется |
| Retry после каждого отказа до COMMIT | Повторный экспорт может выдать тот же «следующий» sequence без gap |
| e2e `export_to_file` | Обновлён под caller-owned txn + порядок A′ |
| ADR-0010 watermark tests | Watermark двигается только вместе с transport commit; нет отдельного второго commit |

Ссылки на конкретные модули тестов — при реализации (unit/integration рядом с
`test_transport_export.py`, `test_adr0010_sync_export.py`, e2e export).

## Статус принятия

**Принято** 2026-09-30 (человек).  
Вариант A′ и инварианты этого addendum считаются финальными; реализация —
#136. Уточнения формулировок под Debian/Linux — в этом PR.
