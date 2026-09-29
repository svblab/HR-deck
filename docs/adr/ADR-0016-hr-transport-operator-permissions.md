# ADR-0016: Оператор transport import/export — HR и разделение с key admin

Статус: Принято  
Дата: 2026-09-29  
Автор: Cursor (формализация продуктового решения по аудиту production-readiness)  
Затронутый EPIC: EPIC-021 (единый диалог «Работа с базой данных»), EPIC-020 (transport exchange)  
Связанные документы: ADR-0007 (§Права, transport crypto), ADR-0010 (directory sync payload),
`domain/permissions.py`, production-readiness audit PR [#128](https://github.com/svblab/HR-deck/pull/128) (finding PR-AUD-001),
PR [#129](https://github.com/svblab/HR-deck/pull/129) (выравнивание реализации)

## Контекст

**Операционная модель продукта.** Сотрудники HR — основные пользователи журнала
доступности персонала: ведение карточек, статусов, справочников, импорт/экспорт
кадровых данных. Роль **Администратор** — техническая/инфраструктурная: учётные
записи, безопасность, журнал действий, шаблоны, резервное копирование/восстановление,
**управление ключами и доверием transport** (TransportKeyStore).

**Transport import/export персонала** (механизм 2, ADR-0007) — штатная операция
обмена уже согласованными business payload между установками при **установленном
доверии** (peer trust, направления, WK). Это не то же самое, что администрирование
ключей: HR использует существующее состояние trust/crypto, но не регистрирует peer
keys, не выполняет bootstrap trust и не re-init цепочек.

ADR-0007 v3 уже разделяет права в §«Права»:

- `Permission.IMPORT_EXPORT` — подготовка и приём transport packages (**HR** и
  Администратор);
- `Permission.MANAGE_ENCRYPTION_KEYS` — bootstrap/trust/key store (**только
  Администратор**).

**Дефект реализации (аудит PR #128, PR-AUD-001).** Сервисы синхронизации
справочников/сотрудников в составе transport (`DirectorySyncImportService`,
`DirectorySyncService`) ошибочно требовали `MANAGE_ENCRYPTION_KEYS` для
планирования/применения импорта и инкрементального export payload. В UI
(EPIC-021) вкладка «Импорт данных» доступна HR (`IMPORT_EXPORT`), из‑за чего
нормальный сценарий обрывался `AuthorizationError` на этапе validate/plan.

**Продуктовое решение (зафиксировано человеком, 2026-09-29).** Политика не
меняется относительно ADR-0007; требуется явная фиксация ответственности и
запрет смешивать transport operations с key administration в коде и будущем UI.

### Разделение ответственности (бизнес vs техника)

| Возможность | HR | Администратор |
| --- | ---: | ---: |
| Transport import персонала (при установленном trust) | Да | Да |
| Transport export персонала (при установленном trust) | Да | Да |
| Штатные операции с БД персонала (карточки, статусы, справочники, файловый импорт/экспорт) | Да | Техподдержка по необходимости |
| Администрирование encryption/key store transport | Нет | Да |
| Trust bootstrap / регистрация peer keys / re-init направлений | Нет | Да |

Таблица **не** выдаёт HR права на key management. Внутреннее использование
шифрования и проверки подписи при import/export **не** превращает операцию в
`MANAGE_ENCRYPTION_KEYS`.

### Почему transport import/export не требует `MANAGE_ENCRYPTION_KEYS`

1. **Семантика permission** (ADR-0007): `IMPORT_EXPORT` уже означает работу с
   transport packages **на базе** существующего trust/state; `MANAGE_ENCRYPTION_KEYS`
   — изменение этого trust/state.
2. **Принцип наименьших привилегий:** HR не должен иметь возможность отзывать
   peer keys, пересоздавать bootstrap identity или ломать направления — это
   инфраструктурный риск.
3. **Разделение слоёв:** crypto receive/export (`TransportReceiveAdminService`,
   `TransportExportAdminService`) и business directory sync
   (`DirectorySyncImportService`, `DirectorySyncService`) — операционный контур
   HR; `TransportKeyAdminService` — отдельный admin facade.

## Рассмотренные варианты

1. **Выдать HR `MANAGE_ENCRYPTION_KEYS`** — отклонено: обходной путь, нарушает
   ADR-0007 и продуктовое разделение ролей.
2. **Оставить transport import только за Администратором** — отклонено:
   противоречит ROADMAP EPIC-021 и операционной модели (HR — основной оператор).
3. **Сохранить ADR-0007 §Права; выровнять код и будущий UI на `IMPORT_EXPORT`
   для directory sync + transport facades** — принято (см. PR #129).

## Решение

1. **`Permission.IMPORT_EXPORT`** авторизует согласованные операции personnel
   transport **import и export** (включая построение/применение directory sync
   plan и инкрементальный export package) для ролей **HR** и **Администратор**.
2. **`Permission.MANAGE_ENCRYPTION_KEYS`** остаётся **только у Администратора**
   и применяется к `TransportKeyAdminService` и аналогичным admin-only операциям
   (bootstrap local identities, peer trust, revocation, re-init — по ADR-0007).
3. Transport operations **не должны** требовать `MANAGE_ENCRYPTION_KEYS` только
   потому, что внутри задействованы шифрование, подпись или TransportKeyStore
   **read/use** в рамках уже установленного trust.
4. Криптографические проверки, freshness/replay gates, атомарность apply,
   журнал действий и прочие инварианты ADR-0007 / `ANCHOR_CORE.md` §4 **сохраняются
   без ослабления**.

### Связь с реализацией

PR [#129](https://github.com/svblab/HR-deck/pull/129) устраняет дефект PR-AUD-001:
в `directory_sync_import.py` и `directory_sync.py` проверка заменена с
`MANAGE_ENCRYPTION_KEYS` на `IMPORT_EXPORT`. Это **выравнивание с политикой
ADR-0007 и настоящего ADR**, а не изменение продуктовой политики.

Настоящий ADR **не** закрывает пробелы operator UI (export, runbook) — см.
GitHub Issue [#130](https://github.com/svblab/HR-deck/issues/130).

## Последствия

- HR может выполнять операционный transport workflow (validate/apply/import path
  и export payload) **без** привлечения IT для каждой поставки пакета, при
  условии что trust уже настроен Администратором.
- Администратор сохраняет ответственность за key/trust lifecycle и восстановление
  после компрометации/потери WK.
- Любой новый код transport UI/сервисов обязан различать:
  - **операторский контур** → `IMPORT_EXPORT`;
  - **key admin контур** → `MANAGE_ENCRYPTION_KEYS`.
- Тесты должны явно фиксировать границу: HR успешен на import/export plan;
  HR отклонён на `TransportKeyAdminService`; Наблюдатель без `IMPORT_EXPORT`.
  (См. `tests/integration/test_transport_hr_authorization.py` в PR #129.)
- `ANCHOR_PROTOCOL.md` §4: точечное уточнение границы прав **без** нового
  permission code — не требует отдельной ADR сверх настоящей, т.к. матрица в
  `permissions.py` для HR уже содержала `IMPORT_EXPORT` и не содержала
  `MANAGE_ENCRYPTION_KEYS`.

## Как проверяется

| Проверка | Тест / артеfact |
| --- | --- |
| HR имеет `IMPORT_EXPORT`, не имеет `MANAGE_ENCRYPTION_KEYS` | `tests/unit/test_permissions_matrix.py` |
| HR: `build_directory_plan`, `build_export_package` | `tests/integration/test_transport_hr_authorization.py` |
| HR: отказ `TransportKeyAdminService.bootstrap_local_identities` | тот же файл |
| Transport facades: `IMPORT_EXPORT` | `tests/integration/test_transport_import_apply.py`, export/receive unit/integration |
| Политика ADR-0007 §Права | ревью + настоящий ADR |
