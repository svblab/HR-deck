# ADR-0007: Протокол доверенного обмена данными между установками (v3)

Статус: Предложено
Дата: 2026-09-08 (v3 final — transaction-authoritative transport state, identity separation)
Автор: архитектурное решение заказчика/тимлида; документировано Cursor
Затронутый EPIC: EPIC-019, EPIC-020

## Контекст

Независимые установки приложения («центр», «филиал» и любые другие peer-копии)
периодически обмениваются снимками данных персонала. Ранние версии ADR-0007
описывали однонаправленную модель «филиал → центр» и смешивали роли
установки с транспортными ключами (`branch_key_id`, `nacl.public.Box`).

Архитектурное ревью и решение заказчика (2026-09-08) фиксируют другую модель:

- протокол оперирует ролями **отправитель (sender)** и **получатель (recipient)**,
  а не постоянным направлением «филиал → центр»;
- канал **дуплексный**: `A → B` и `B → A` — два независимых направления;
- криптография транспорта **отделена** от шифрования локальной БД;
- идентичность установки для аутентификации — **signing identity** и отдельно
  **bootstrap encryption identity**; транспортный ключ `WK` — не identity;
- каждый пакет использует свежий симметричный ключ файла `SK`; цепочка
  транспортных ключей `WK` эволюционирует **отдельно в каждом направлении**.

**Задача ADR:** зафиксировать свойства и инварианты протокола, достаточные
для согласованной реализации EPIC-019/020, **не** предписывая конкретные
API библиотек, схему таблиц БД или детали UI bootstrap.

**Четыре свойства протокола** (сохраняются от v2):

1. **Confidentiality** — посторонний не может прочитать пакет.
2. **Integrity** — пакет нельзя незаметно изменить в пути.
3. **Authenticity** — получатель криптографически устанавливает, от какой
   **доверенной установки-отправителя** пришёл пакет (через долгоживущую
   подписывающую идентичность), а не по недоверенным полям заголовка.
4. **Freshness** — устаревший или повторно использованный пакет не может
   незаметно затереть более свежее состояние **в том же направлении**.

## Рассмотренные варианты (история)

1. **`SealedBox` / анонимное шифрование только публичным ключом получателя**
   (v1) — **отклонено**: нет подлинности отправителя.
2. **`nacl.public.Box` как единственный примитив** (v2) — **отклонено** как
   итоговая модель: смешивает транспортную идентичность с ключом шифрования,
   не поддерживает независимые duplex-цепочки и per-package `SK`.
3. **Разделённые домены: подпись + SK на пакет + WK-цепочка на направление**
   (v3) — **выбрано** заказчиком.

## Разделение криптографических доменов

### 1. Шифрование локальной БД (существующее)

- Мастер-ключ SQLCipher + sidecar keywrap (`personnel.db.keywrap`) по
  **ADR-0002 / ADR-0003**.
- Защищает **только** локальную базу персонала на данной установке.
- **Не** используется для транспортного шифрования и **не** смешивается с
  транспортными ключами.

### 2. Signing identity (аутентификация пакетов)

**Signing identity** — долгоживущая асимметричная пара **только для подписи**
транспортных пакетов:

```text
Signing identity
    private signing key      — подписывает исходящие пакеты (локально)
    public verification key  — проверяет подпись входящих пакетов (peer trust)
```

- У каждой установки — **собственная** signing identity (алгоритм/API —
  implementation model, см. `ANCHOR_PROTOCOL.md` §4).
- **Public verification key** peer-а устанавливается при **одноразовом ручном
  bootstrap** (см. ниже).
- Это **идентичность установки в протоколе**, но **не** bootstrap encryption
  identity, **не** `WK`, **не** `key_id`.

**Инвариант:** signing и bootstrap encryption — **разные** криптографические
назначения; implementation **не** смешивает их в одну роль/ключ.

### 3. Bootstrap encryption identity (первый конверт направления)

**Bootstrap encryption identity** — долгоживущая асимметричная пара **только
для защиты первого конверта** каждого направления (asymmetric wrap первого
`WK`):

```text
Bootstrap encryption identity
    private decryption key   — локально у получателя
    public encryption key    — доверенный peer использует при первом пакете
                               направления sender → recipient
```

- Public encryption key получателя передаётся peer-у при **manual bootstrap**.
- Используется **только** для первого пакета направления; последующие пакеты
  — через цепочку `WK`, не через bootstrap encryption.
- **Не** используется для подписи и **не** заменяет signing identity.

### 4. Ключ файла / полезной нагрузки (`SK_n`)

- На **каждый** экспортируемый пакет — **новый** случайный симметричный ключ
  `SK_n` (архитектурное требование: AES-256-GCM или эквивалент по
  AEAD-семантике).
- `SK_n` шифрует **только** полезную нагрузку пакета (business payload).

**AES-GCM nonce/IV (инвариант):** каждый вызов AES-GCM с `SK_n` **обязан**
использовать nonce/IV, **уникальный для данного ключа** `SK_n`; nonce/IV
передаётся/обрабатывается как **authenticated cryptographic metadata**
(AEAD). Длина nonce, RNG API — **implementation model**.

### 5. Транспортный / конвертный ключ (`WK_n`)

- Для **каждого направления** `sender → recipient` — **независимая** цепочка
  симметричных транспортных ключей `WK_1 → WK_2 → WK_3 → …`.
- `WK_n` — **не** идентичность установки; это одноразовый (в смысле роли в
  цепочке) секрет для защиты **конверта**, содержащего `SK_n`, `WK_{n+1}` и
  необходимые метаданные.
- У каждого `WK_n` есть **уникальный не-секретный** `key_id` — см. ниже.

**AES-GCM nonce/IV (инвариант):** каждый вызов AES-GCM с `WK_{n-1}` для
конверта **обязан** использовать nonce/IV, **уникальный для данного ключа**
`WK_{n-1}`; nonce/IV — authenticated cryptographic metadata (AEAD).

## Роли протокола и duplex-канал

Протокол **не** моделирует постоянную связь «филиал → центр».

Между двумя установками `A` и `B` существуют **два независимых направления**:

```text
A → B   (sender=A, recipient=B)
B → A   (sender=B, recipient=A)
```

У каждого направления — **своя** цепочка `WK`, **свой** монотонный `sequence`,
**своё** текущее transport-state. Количество пакетов и ключей в одном
направлении **не обязано** совпадать с другим (филиал может слать часто,
головной офис — редко).

**Запрещено:** искусственно синхронизировать или объединять transport-state
обоих направлений в один глобальный счётчик/ключ.

## Одноразовый ручной bootstrap доверия

Перед нормальной эксплуатацией каждая пара установок проходит **одноразовую**
ручную процедуру установления доверия (на весь обычный жизненный цикл, пока
ключи не скомпрометированы и не требуют замены):

- каждая сторона передаёт другой стороне **доверенный публичный материал**:
  **public verification key** (signing identity peer-а) и **public encryption
  key** (bootstrap encryption identity peer-а для первых конвертов);
- передача — **только** через доверенный out-of-band канал (курьер, TLS с
  проверкой отпечатка, и т.п.);
- **UI и операционный workflow bootstrap — вне рамок этой ADR.**

**Инвариант:** начальное доверие устанавливается **вручную/out-of-band**.
Обычная передача пакетов **не** требует повторной ручной сверки отпечатков
на каждый пакет.

**Первый `WK` каждого направления** создаётся автоматически при **первом
исходящем пакете** этого направления; он **не** переносится вручную при
bootstrap.

## Цепочка WK в одном направлении

Для направления `sender → recipient`:

```text
WK1 → WK2 → WK3 → …
```

### Первый пакет направления

```text
SK1  = fresh random AES-256-GCM key
WK1  = fresh random 256-bit transport key
C1   = AES-GCM(SK1, payload)
Envelope1 = материал, защищённый **public encryption key** получателя
            (bootstrap encryption identity), достаточный для восстановления WK1
Package1  = подписан **private signing key** отправителя; содержит C1,
            Envelope1, и недоверенные метаданные маршрутизации
```

### N-й пакет (N > 1)

```text
SKn  = fresh random AES-256-GCM key
WKn  = fresh random 256-bit transport key
Cn   = AES-GCM(SKn, payload)
Envelopen = AES-GCM(WK{n-1}, SKn + WKn + required metadata)
Packagen  = подписан **private signing key** отправителя
```

Тот же шаблон продолжается для всех последующих пакетов **в этом направлении**.

### Модель перехода transport-state (направление)

Conceptual state machine для **принятого** направления `sender → recipient`:

```text
Package #1 (sequence = 1):
    envelope protected by bootstrap encryption (peer public encryption key)
    → on accept: establishes WK1 as current transport key

Package #2 (sequence = 2):
    envelope protected using WK1
    → on accept: establishes WK2 as current transport key

Package #3 (sequence = 3):
    envelope protected using WK2
    → on accept: establishes WK3 as current transport key
    …
```

**Инвариант направления после accept пакета с `sequence = N`:**

```text
accepted sequence for direction = N
current transport key for direction   = WKN
current key_id                      = id(WKN)
```

**Следующий valid-next пакет** (`sequence = N+1`) **обязан**:

```text
use WKN to protect its envelope
→ establish WK(N+1)
→ atomically advance persisted state to sequence N+1 / WK(N+1)
   (inside the same package-acceptance DB transaction)
```

`chain_id` **не** вводится. `key_id` остаётся уникальным не-секретным
идентификатором соответствующего `WK`.

Конкретные форматы JSON/binary, поля authenticated metadata и выбор
криптобиблиотеки — **implementation model** (EPIC-019/020), при условии
сохранения инвариантов выше и прохождения ADR-триггеров зависимостей.

## `key_id` транспортного ключа

- Каждому `WK_n` присваивается **уникальный не-секретный** `key_id`.
- `key_id` — **идентификатор**, не секретный ключ.
- `key_id` **не** является идентичностью установки и **не** должен
  кодировать роль «филиал/центр» или семантику организационной структуры,
  если implementation не докажет необходимость.
- Получатель **обязан** находить `WK` по `key_id` через **TransportKeyStore**
  (см. ниже) — **без** перебора всех сохранённых ключей.

```text
package metadata (untrusted until verified)
    → key_id
    → TransportKeyStore lookup (authoritative DB state)
    → WK material for decrypt
    → cryptographically authenticate package
    → decrypt/authenticate envelope
    → obtain SK, next WK, authenticated fields
```

`key_id` может присутствовать в открытых метаданных пакета.

## TransportKeyStore и transaction-authoritative persistence

**TransportKeyStore** — **концептуальная** абстракция/сервис (EPIC-019) для
lookup и administration transport keys/state. **Не** требует отдельного
физического `keys.enc`, если это нарушает atomicity.

### Authoritative persistence invariant

**Authoritative transport state** и transport key material, необходимые для
**package acceptance**, **обязаны** persist внутри **той же ACID-транзакции
SQLite**, что и:

```text
business changes
+ package acceptance / replay record
+ transport direction state (sequence, current key_id)
+ newly established WK material for next packet
+ audit event
```

**Предпочтительная архитектура** (согласована с repository model проекта):

```text
personnel.db (encrypted, ADR-0002/0003)
    ├── business data
    ├── package acceptance / replay state
    ├── transport direction state (per sender→recipient)
    ├── current / historical WK material (encrypted at rest in DB)
    ├── peer trust records (signing + bootstrap encryption public keys)
    └── related transport metadata (revoked/compromised flags, …)
```

Implementation **может** именовать слой `TransportKeyStore`, но **mutable
authoritative state не живёт** в отдельном sidecar-файле, который нельзя
атомарно commit вместе с `personnel.db`.

**Если** когда-либо вводится дополнительный external file — он **не** может
стать independently authoritative mutable source of transport state **без**
явно спроектированной crash-safe atomicity (two-phase commit **не**
проектируется в этой ADR).

### At-rest protection

- **Plaintext `WK` на диске не хранится.**
- Transport key material и metadata защищены **существующей** моделью
  шифрования БД (SQLCipher master key + `personnel.db.keywrap`, ADR-0002/0003).
- Transport crypto **логически отделено** от «мастер-ключа как роли», но
  **физически co-located** в encrypted `personnel.db` для atomic commit.

### Backup / restore

Authoritative transport state **включён автоматически** при backup/restore
`.db` + `.keywrap` — отдельный обязательный sidecar KeyStore-file **не**
требуется при DB-centric модели. `BackupService` **обязан** сохранять
**полный** encrypted DB snapshot (реализация — EPIC-019/012).

### Содержимое (conceptual)

TransportKeyStore **управляет** (внутри DB transaction boundary):

- active/historical `WK` и direction state;
- `package_id` / replay records;
- imported peer **public verification keys** и **public encryption keys**;
- revoked/compromised/lost metadata.

**Инвариант:** **historical** `WK` **не** становится active автоматически.
Точная SQL-схема — **implementation detail**.

## Потеря, компрометация и исторические ключи

Различать явно:

| Состояние | Смысл |
|---|---|
| **active** | текущий `WK`/state для продолжения цепочки направления |
| **historical** | ключ/state только для расшифровки уже полученных пакетов |
| **lost** | секрет `WK` или state, необходимый для **продолжения** цепочки, утрачен |
| **compromised** | ключ/state считается скомпрометированным по решению администратора |

**Потеря текущего `WK` для направления:**

```text
current WK lost
  → transport chain for that direction is broken
  → no brute-force recovery
  → no automatic fallback to an older WK
  → manual re-initialization required for that direction
```

**Запрещено:** молча откатываться на старый `WK` для продолжения текущей
цепочки.

**Сохраняется:** всё, что **не** потеряно и **не** скомпрометировано:

- исторические `WK` (для чтения старых пакетов);
- signing keys (verification keys retained for audit);
- bootstrap encryption keys (public encryption keys of peers);
- архивные зашифрованные файлы;
- прочий валидный криптоматериал.

Re-initialization **не** означает автоматическое уничтожение выжившего
материала.

### Компрометация transport/signing ключей (минимальный lifecycle)

**Инвариант:** скомпрометированный ключ **не остаётся доверенным** только
потому, что физически присутствует в TransportKeyStore / DB records.

| Событие | Минимально безопасное поведение |
|---|---|
| **Compromised active `WK`** | Пометить `key_id`/direction state как **revoked/compromised**; **запретить** продолжение цепочки через этот ключ; **manual re-initialization** направления (или admin-defined replacement) |
| **Compromised signing identity** | Revoke trust **public verification key** peer-а; **отклонять** новые пакеты с этой подписью; historical packages **могут** верифицироваться retained verification key для audit |
| **Compromised bootstrap encryption identity** | Revoke trust **public encryption key**; re-bootstrap out-of-band для новых first-envelope на affected directions |
| **Re-init / replacement** | **Не** уничтожать автоматически historical `WK`, архивные пакеты, signing material, не помеченный compromised |
| **Historical key after compromise** | Остаётся **historical** — только decrypt/verify старых пакетов; **не** становится active `WK` автоматически |

**Запрещено:** silent fallback на более старый `WK`; автоматическое
«исправление» transport-state; продолжение цепочки через ключ, помеченный
compromised/lost.

Детальный operational UI/workflow revocation (экраны, runbook, dual-control)
— **implementation** (EPIC-019); ADR фиксирует только security invariants.

### Потеря local signing private key

**Lost signing identity** (утрачен **private signing key** локальной
установки) — **отдельно** от lost `WK` и от compromise:

```text
lost signing private key
  → cannot create authenticated outgoing packages
  → no automatic silent replacement
  → administrator performs manual re-bootstrap / key replacement
  → peer trusts replacement public verification key only after explicit
     trusted out-of-band verification
```

- Historical packages, подписанные **старой** signing identity, **могут**
  оставаться verifiable/auditable, если **public verification key** сохранён
  (historical trust record).
- **Запрещено:** silent auto-rotation signing identity без explicit peer
  re-verification.

## Duplex: независимое transport-state

Для пары установок `A` и `B` conceptually:

```text
A → B:  current_key_id, sequence, applied packages, …
B → A:  current_key_id, sequence, applied packages, …
```

Implementation **должен** persist это **внутри** encrypted `personnel.db`
(TransportKeyStore); ADR фиксирует **инвариант**, а не SQL-схему.

## Формат пакета (архитектурный уровень)

Пакет содержит как минимум:

1. **Недоверенные метаданные маршрутизации** (открытый текст) — достаточные
   для lookup `key_id` / direction / `protocol_version`, **но не
   доверенные** до криптопроверки.
2. **Подпись** identity-ключом отправителя — покрывает все security-relevant
   части пакета (см. «Аутентифицированные поля»).
3. **Зашифрованный конверт** под `WK_{n-1}` (или bootstrap asymmetric wrap
   для первого пакета направления).
4. **Зашифрованную полезную нагрузку** под `SK_n`.

После успешной расшифровки и проверки подписи получатель **доверяет**
аутентифицированным полям внутри конверта/payload (sender peer id,
`package_id`, `sequence`, business data и т.д.).

## Аутентифицированные поля (инвариант протокола)

Подпись отправителя и authenticated metadata конверта **обязаны** защищать
все security-relevant данные, необходимые для предотвращения:

- **подмены отправителя** (sender substitution);
- **подмены получателя** (recipient substitution);
- **манипуляции replay** (`package_id`, признаки повторной доставки);
- **манипуляции sequence** (номер/порядок в направлении);
- **манипуляции key-reference** (`key_id`, ссылки на transport-state);
- **манипуляции ciphertext** (конверт, payload, AEAD tags).

**Минимальный набор authenticated полей** (conceptual — exact names и
canonical serialization — **implementation model**):

| Область | Примеры полей |
|---|---|
| Protocol routing | `protocol_version`, direction (`sender`/`recipient` peer id), `key_id` used for envelope |
| Package identity | `package_id`, `sequence` |
| Envelope chain | `SK_n` reference / wrapped material, `WK_{n+1}` / next `key_id`, envelope AEAD |
| Payload | ciphertext under `SK_n` (или его authenticated hash) |
| Trust context | signing identity id (или fingerprint) отправителя |

Cleartext routing metadata **может дублировать** эти значения для lookup, но
**не является источником доверия** до успешной проверки подписи и
расшифровки конверта. Любое расхождение cleartext ↔ authenticated → **отказ**.

Конкретный wire format, canonical bytes для подписи и выбор crypto API —
**implementation model** (EPIC-019/020), при условии сохранения инвариантов
выше.

### Процедура приёма и trust boundary

**Security invariant (authoritative):**

> Ни одно значение из конверта или payload **не доверяется** как
> security-sensitive или business metadata, пока пакет **не прошёл** required
> cryptographic authentication checks.

**Conceptual pipeline** (exact crypto operation order — **implementation
model**, если выбранная construction требует иного порядка, при сохранении
invariant выше):

```text
read untrusted routing metadata
→ select only pre-established trusted key material (by key_id / direction)
→ cryptographically authenticate the package (signature + AEAD)
→ decrypt/authenticate envelope
→ decrypt/authenticate payload
→ validate authenticated metadata against cleartext routing metadata
→ freshness/replay classification
→ structural / business validation
→ confirmation gate if required (whole package, outside DB transaction)
→ atomic DB transaction (business + package + transport state + audit)
```

**Запрещено:** использовать cleartext header или partially decrypted envelope
как источник доверия до завершения authentication checks.

**Confirmation / DB:** шаги после confirmation gate — см. «Атомарность
пакета»; **no UI inside** DB transaction.

## Freshness, replay и идемпотентность

Для **каждого направления** отдельно import orchestrator классифицирует
входящий пакет **до** `BEGIN TRANSACTION`:

| Класс | Условие | Поведение |
|---|---|---|
| **Exact replay** | тот же `package_id`, уже **успешно принятый** | **Идемпотентный успех** — см. ниже |
| **Stale sequence** | новый `package_id`, но `sequence` ≤ max принятого | **Отклонить** |
| **Consumed sequence** | новый пакет с уже использованным `sequence`, не exact replay | **Отклонить** |
| **Valid next** | следующий допустимый пакет направления, все gates пройдены | **Принять** (atomic apply) |
| **Missing/lost transport key** | `key_id` не найден, или ключ/state помечен **lost/revoked** для продолжения цепочки | **Отклонить** — без перебора, без fallback на historical `WK` |
| **Malformed / crypto invalid** | parse, signature, decrypt, structural failure | **Отклонить** до DB transaction |

Точное представление `package_id`, `sequence`, журнала принятых пакетов —
**implementation detail** (authoritative tables в `personnel.db`).

### Идемпотентность exact replay (authoritative invariant)

> Повторная доставка **уже успешно принятого** пакета (`package_id`) должна
> быть идемпотентной и **не** дублировать business data, audit events
> (кроме явной replay-метки), transport-state advancement или изменения
> status-history.

При **exact replay**:

- **не** повторять business DB writes (create/update employee, whitelist fields);
- **не** повторять вызовы `StatusHistoryService`, создающие новые записи
  истории;
- **не** продвигать `sequence`, **не** persist новый `WK_{n+1}` (transport
  state уже зафиксирован при первом accept);
- **можно** записать audit «replay observed» / обновить replay metadata —
  **одна** явная replay-запись на операцию, без side effects на domain state.

**Запрещено:** silent business-data reconciliation или «мягкое слияние» при
replay — только идемпотентное no-op относительно уже принятого состояния.

### StatusHistoryService и package-level idempotency

Существующий `StatusHistoryService` (EPIC-006) может иметь **иную**
granularity (например, `ConfirmationRequiredError` на уровне одного статуса).
Для transport import **authoritative** invariant — **package-level**
idempotency выше.

**Implementation work (EPIC-020, не в scope этой ADR):** import orchestrator
**обязан** оборачивать status mutations так, чтобы при exact replay они
**не выполнялись**; при первичном accept — вызывать сервис **внутри** единой
package transaction. Если confirmation required — **весь пакет** pending до
confirm (см. «Атомарность пакета»), без silent auto-correction overlaps.

## Атомарность одного принятого пакета

### Пакет — атомарная единица принятия

**Инвариант:** transport package — **единственная** атомарная единица
принятия на уровне протокола и БД.

- Пакет **либо принят целиком**, **либо отклонён**, **либо ожидает
  confirmation целиком** — **без** partial application.
- Business-record-level partial acceptance **запрещена**: если **любая**
  строка payload не проходит validation, или любая операция (в т.ч. статус)
  требует explicit confirmation — **весь пакет** не принимается до
  resolution; transport-state **не** продвигается.
- Получатель **не** «потребляет» `WK` и **не** продвигает `sequence` только
  потому, что расшифровал или просмотрел пакет.
- **Запрещено:** silent auto-correction status history / overlaps при import.

**Confirmation-required packages:** если pre-DB validation обнаруживает
`ConfirmationRequiredError` (или эквивалент) для **любой** строки — пакет
→ **pending** **вне** DB transaction. Пользователь подтверждает или
отклоняет **весь пакет**. После confirm — **полная повторная** pre-DB
validation, затем **один** atomic apply. **Никакого** UI/user interaction
**внутри** DB transaction.

**Будущий partial business accept:** если когда-либо потребуется принимать
часть записей — это **отдельный** protocol/application-level concept (напр.
отправитель формирует несколько пакетов); **не** ослабляет package atomicity.

### Одна DB transaction на успешно принятый пакет

**Инвариант:** один **успешно принятный** пакет = **одна атомарная транзакция
БД**.

Криптография, validation и confirmation выполняются **до** `BEGIN
TRANSACTION`:

```text
parse
→ read untrusted routing metadata
→ select trusted key material (TransportKeyStore / key_id)
→ cryptographically authenticate package
→ decrypt/authenticate envelope and payload
→ validate authenticated vs cleartext metadata
→ structural validation
→ business validation (external_id+ФИО, whitelist, status plans, …)
→ freshness/replay classification
→ [if confirmation required: pending UI → user confirm/reject whole package]
→ [if confirmed: re-run pre-DB validation]
→ BEGIN TRANSACTION
→ apply all business changes (full package)
→ persist package acceptance / replay record
→ persist transport state (sequence N+1, WK(N+1), key_id) — first accept only
→ persist audit event
→ COMMIT
```

**Package-import orchestrator** (EPIC-020) **владеет** единственной
transaction boundary. Domain/services/repositories, используемые при accept,
**обязаны** поддерживать transaction-aware composition (shared connection /
unit-of-work / deferred commit — **implementation model** после inspect
service boundaries). **Запрещено:** internal `COMMIT` внутри вызываемых
services во время package apply.

При любой ошибке на этапе DB mutation:

```text
ROLLBACK
```

Пакет остаётся **непринятым**; transport-state **не** продвигается.

## Владение полями — whitelist (сохранено от v2)

Импорт transport-payload обновляет **только** перечисленные поля существующей
карточки (при совпадении `external_id`+ФИО). Всё остальное — не трогается.

**Peer-owned (заменяются данными отправителя):** ФИО, должность, филиал,
департамент, отдел, тип занятости, контакты, домашний адрес, номер
страхования, текущий статус доступности (через `StatusHistoryService`).

**Local-only:** `id`, `external_id` (immutable после первого создания),
`created_at`, `is_archived` (только через штатный статус «Уволен/неактивен»),
локальные заметки центра, audit-метаданные.

Статус «в архиве» **не** передаётся полем напрямую.

## Зависимость от ADR-0006 (`external_id`) и граница reconciliation

Transport merge опирается на **`external_id` + ФИО** для **deterministic**
сопоставления сотрудников. **`external_id` определён в ADR-0006** (статус на
момент v3: **Предложено**). Transport import **не** invent альтернативный
cross-installation identity mechanism.

**EPIC-020 не начинается**, пока:

- ADR-0006 **не принята** человеком, **и**
- миграция/генерация `external_id` **не реализована** в коде.

### Разделение transport import vs reconciliation (ADR-0006)

```text
Transport import (ADR-0007)          Separate reconciliation (ADR-0006)
────────────────────────────         ───────────────────────────────────
external_id identity                 LOW confidence name match
authenticated package                AMBIGUOUS match
freshness / replay                   identifier conflict (external_id vs ФИО)
atomic whole-package apply           manual user selection / wizard flows
whitelist field merge
```

**Transport import обязан:**

- **match** только по **`external_id` + ФИО** (create/update per whitelist);
- **reject** malformed/missing `external_id` — **без** silent fuzzy
  reconciliation внутри transport path;
- **reject** identifier conflict (`external_id` найден, ФИО не совпадает) —
  **без** auto-resolution;
- **не** становиться multi-master merge engine между peer-ами.

Fuzzy reconciliation (`LOW`, `AMBIGUOUS`), manual user selection и
identifier-conflict workflows остаются **вне** transport import — в
механизмах ADR-0006 / EPIC-018, **не** в silent transport apply.

Дополнительно: установка **может** хранить для каждого `external_id`
идентификатор **последнего доверенного peer-отправителя** (signing identity /
trust record — не `key_id` и не `WK`), чтобы предупреждать HR, если тот же
`external_id` впервые приходит от другого peer. Это **предупреждение**, не
автоблокировка (multi-master merge по-прежнему вне скоупа, см. ниже).

## Права

- `Permission.MANAGE_ENCRYPTION_KEYS` (новое) — bootstrap/trust management,
  TransportKeyStore administration, manual re-initialization, import/revocation
  peer signing and bootstrap encryption public keys, управление historical keys.
  **Только Администратор.**
- `Permission.IMPORT_EXPORT` (существующее) — подготовка и приём transport
  packages с использованием уже установленного trust/state. **HR** (и
  Администратор).

## Журнал действий

Каждый export/import/replay — отдельная запись audit log (метаданные операции:
direction, `package_id`, `sequence`, peer sender id, `key_id` involved,
result: accepted / rejected / pending / replay, classification). **Без**
персональных данных payload в journal details beyond entity ids already
permitted elsewhere.

## Что сознательно остаётся вне рамок этой ADR

- **UI bootstrap**, экранные формы, operational runbook — implementation.
- **Точная SQL-схема transport tables**, wire formats — implementation.
- **Выбор криптобиблиотеки** и pinned algorithms — implementation model при
  соблюдении `ANCHOR_PROTOCOL.md` §4 (новая зависимость → ADR принята до PR).
- **Multi-master merge** между разными peer-ами, утверждающими конфликтующие
  данные одного `external_id` — по-прежнему **вне скоупа** (`ANCHOR_CORE.md`
  §6). Freshness защищает **направление**, не арбитрирует между peer-ами.

## Тесты (архитектурный контракт для EPIC-019/020)

| Область | Пример проверки | Спецификация |
|---|---|---|
| Signing vs bootstrap | Signing и bootstrap encryption — разные trust records/roles | SPECIFIED |
| Auth before trust | Metadata из envelope/payload не trusted до crypto auth | SPECIFIED |
| AES-GCM nonce SK | Unique nonce per `SK_n` invocation | SPECIFIED |
| AES-GCM nonce WK | Unique nonce per `WK` envelope invocation | SPECIFIED |
| WK state transition | Accept seq N → current WKN; next uses WKN → WK(N+1) atomically | SPECIFIED |
| Transport DB atomicity | Transport state commits in same DB txn as package accept | SPECIFIED |
| Signing auth | Пакет с неверной/чужой подписью отклоняется | SPECIFIED |
| Bootstrap first envelope | Первый пакет направления — bootstrap encryption, без prior WK | SPECIFIED |
| WK chain | N-й пакет использует `WK_{n-1}`; после accept доступен `WK_n` | SPECIFIED |
| key_id lookup | Receiver находит ключ по `key_id` без перебора всех ключей | SPECIFIED |
| Wrong key_id | Неизвестный `key_id` → понятный отказ | SPECIFIED |
| Duplex independence | Прогресс `A→B` не меняет state `B→A` | SPECIFIED |
| Lost current WK | Продолжение цепочки без re-init невозможно | SPECIFIED |
| Lost signing key | Нет исходящих auth packages без manual replacement + peer verify | SPECIFIED |
| No silent rollback | Старый historical WK не становится active автоматически | SPECIFIED |
| Stale sequence | Устаревший sequence отклоняется | SPECIFIED |
| Replay idempotency | Повтор `package_id` не дублирует business/status/transport state | SPECIFIED |
| Replay no status dup | Exact replay не вызывает новых StatusHistoryService writes | SPECIFIED |
| Missing key_id | Unknown/lost/revoked `key_id` → отказ без fallback | SPECIFIED |
| Crypto invalid | Bad signature/decrypt → отказ до DB | SPECIFIED |
| Package atomicity | Любая invalid/conflict строка → весь пакет rejected/pending | SPECIFIED |
| ADR-0006 boundary | No fuzzy reconcile / auto conflict resolve in transport import | SPECIFIED |
| Confirmation gate | Confirm-required → whole package pending, re-validate after confirm | SPECIFIED |
| No UI in transaction | DB transaction без user interaction | SPECIFIED |
| Transaction composition | Orchestrator owns single COMMIT; services no internal commit | SPECIFIED |
| Atomic apply | Сбой mid-transaction → rollback, пакет не принят | SPECIFIED |
| Compromised key | Revoked key не используется для active transport/trust | SPECIFIED |
| Transport backup | Restore `.db`+keywrap → business + authoritative transport state | SPECIFIED |
| Whitelist fields | Local-only поля не меняются import-ом | SPECIFIED |
| Status service | Статусы через `StatusHistoryService` внутри package transaction | SPECIFIED |
| Admin permission | Key management только admin | SPECIFIED |
| Authenticated coverage | Tamper cleartext vs signed fields → reject | SPECIFIED |

## Оставшиеся вопросы (implementation model only)

Следующие пункты **не** блокируют архитектурный текст v3; уточняются при
реализации EPIC-019/020:

1. **Canonical serialization** для подписи и envelope AEAD (exact bytes,
   field order) — при сохранении инвариантов «Аутентифицированные поля».
2. **Operational UI/runbook** для revocation/compromised keys и direction
   re-init (экраны, тексты, dual-control) — EPIC-019.
3. **Конкретный механизм** transaction-aware composition (shared `Connection`,
   unit-of-work, repository callbacks) — EPIC-020 после inspect service
   boundaries; **инвариант** уже зафиксирован выше.

## История решений

| Версия | Дата | Суть |
|---|---|---|
| v1 | 2026-09-06 | SealedBox confidentiality only — отклонена |
| v2 | 2026-09-07 | Box, branch/center, branch_key_id — заменена v3 |
| v3 | 2026-09-08 | Duplex sender/recipient, SK+WK chains, TransportKeyStore in DB, signing/bootstrap separation |
