# ADR-0007 Addendum — Transport generation (epoch) per direction

Статус: Предложено  
Дата: 2026-09-27  
Автор: Cursor (draft from Pre-021 transport gate)  
Затронутый EPIC: EPIC-019, EPIC-020; prerequisite for EPIC-021 import UI  
Relates to: ADR-0007 v3 (принято), EPIC-020 slices 020-B…020-F

## Контекст

ADR-0007 v3 задаёт **монотонный `sequence` на всё время жизни направления**
`sender → recipient`, уникальность принятых пакетов
`(direction_id, sequence)` и ручной `reinit_direction` при потере текущего `WK`.
Реализация EPIC-019/020 следует этой модели.

Операционный сценарий **transport-chain reinitialization** (потерянный пакет,
согласованное возобновление) требует начать **новую цепочку** с `sequence = 1`
и новым `WK`, **не** создавая новый out-of-band trust bootstrap. При этом
исторические принятые пакеты и уникальный индекс
`(direction_id, sequence) WHERE accepted` **запрещают** повторное принятие
`sequence = 1` в той же «эпохе» lifetime-sequence.

`chain_id` в v3 **не** вводится; вводится отдельное поле **`generation`**
(поколение/epoch направления).

## Решение

**Позиция в протоколе:** `transport position = (generation, sequence)`.

| Инвариант | Было (v3 + код до addendum) | Стало |
|-----------|----------------------------|--------|
| Монотонность | `sequence` на lifetime направления | `generation` монотонен на направление; `sequence` монотонен **внутри** generation |
| Reinit | `accepted_sequence := 0`, `current_wk := NULL`, `reinit_required` | **`generation += 1`** атомарно с тем же сбросом seq/WK/status |
| Первый пакет нового generation | (не определено) | **`sequence = 1`**, bootstrap envelope, новый `WK` |
| Trust bootstrap | OOB peer keys | **Без изменений** — reuse `transport_peer_trust` |
| `package_id` | replay identity | Без изменений |
| `key_id` | WK crypto identity | Без изменений |

### Trust bootstrap vs transport-chain reinit

1. **Out-of-band trust bootstrap** — регистрация peer signing + bootstrap encryption
   keys (`transport_peer_trust`). Однократно до компрометации.
2. **Transport-chain reinit** — `reinit_direction`: `generation += 1`, тот же trust,
   первый пакет нового generation с `envelope_key_id = bootstrap`.

### Состояние направления (получатель / отправитель)

```text
G0: accepted packages (G0,1..N), current WK = WKn, status active
  → reinit_direction (одна транзакция):
      generation := G0 + 1
      accepted_sequence := 0
      current_wk_id := NULL
      direction_status := reinit_required
  → первый принятый или исходящий пакет (G1, seq=1, bootstrap):
      новый WK (predecessor_key_id = NULL, generation_established = G1)
      direction_status := active
  → далее (G1, 2), (G1, 3), …
```

Отправитель хранит **свою** `generation` на строке направления `local → peer`;
согласование reinit — **вне полосы** (human-coordinated), как в v3 для
операционных протоколов.

### Freshness (до `BEGIN`, import validation)

| Класс | Условие | Действие |
|-------|---------|----------|
| Exact replay | тот же `package_id`, уже accepted | Идемпотентный успех (020-F) |
| Old generation | `generation < direction.generation` | Отклонить |
| Future generation | `generation > direction.generation` | Отклонить (только reinit повышает generation) |
| Same-gen stale | `generation == direction.generation` и `sequence != max_in_gen + 1` | Отклонить |
| Valid next | `generation == direction.generation` и `sequence == max_in_gen + 1`, crypto/validation OK | Принять (atomic apply) |

### Уникальность

Принятые пакеты: **UNIQUE** `(direction_id, generation, sequence)` WHERE
`classification = 'accepted'`. `package_id` остаётся глобально UNIQUE.

### Wire / `protocol_version`

- **`TRANSPORT_PROTOCOL_VERSION = 2`**: authenticated routing + AAD + signing
  включают поле `generation`.
- **Dual-read:** пакеты v1 без поля `generation` интерпретируются как
  **`generation = 0`**. Новые экспорты **всегда** v2.
- Подмена `generation` в cleartext без согласованной подписи/AAD → reject.

### Миграция

Существующие строки: `generation = 0` на `transport_direction_state` и
`transport_package_records`. Опционально `transport_wk_keys.generation_established`.

### Почему до EPIC-021

Вкладка «Импорт данных» не должна кодировать lifetime-only `sequence` или
ad-hoc reinit. UI потребляет стабильный контракт `(generation, sequence)` и
freshness из этого addendum.

## Последствия

- Требуется миграция схемы и обновление EPIC-020 export/import/reinit.
- Peers должны согласовать reinit; смешанный v1/v2 допустим только при
  dual-read (v1 ⇒ G=0) и **до** reinit на получателе с G>0.
- Backup/restore: generation в `personnel.db` — сохраняется с полным backup DB.

## Как проверяется

Матрица тестов в `tests/integration/test_transport_generation_epoch.py` и
расширения unit-тестов transport export/validation/keys/canonical.

## Статус принятия

**Предложено.** Реализация в ветке `epic/EPIC-020-transport-generation-epoch`
согласована с этим текстом; финальный протокол — после принятия человеком.
