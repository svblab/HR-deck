# Журнал доступности персонала

Локальное офлайн-приложение для учёта доступности персонала (Linux / Debian·Ubuntu).
Источник требований — `TZ_HR_uchet_dostupnosti.docx`. Правила работы — в `docs/`.

## Быстрый старт (разработка)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
personnel-availability      # или: python -m ui
```

На CI и headless-окружении окно запускается с `QT_QPA_PLATFORM=offscreen`.

## Структура

См. `docs/ANCHOR_CORE.md` §5: `src/{domain,data,services,ui,reports}`, `migrations/`, `tests/`, `packaging/`.

## E2E mechanics (dual-peer, headless)

Service-layer validation of transport exchange, backup/restore, one corrupted
package, EPIC-018 conversion, and EPIC-007 «requires attention» between two
isolated peers. See [`tests/e2e_mechanics/README.md`](tests/e2e_mechanics/README.md).

```bash
docker compose -f tests/e2e_mechanics/docker-compose.yml run --rm e2e-runner
```

## Документация

Порядок чтения — `docs/README.md`. Текущий эпик — `docs/ROADMAP.md` (EPIC-001).
