# Packaging (EPIC-015)

Сборка `.deb`, ярлык в меню и раздельные каталоги данных.

Ожидаемый пакет: `personnel-availability`.

**Целевой релиз для проверки:** Ubuntu 24.04 LTS.

## Сборка (Linux)

```bash
chmod +x scripts/build-deb.sh
./scripts/build-deb.sh
```

## Зависимости Python

`sqlcipher3` и `argon2-cffi` **не** поставляются как системные apt-пакеты на
Ubuntu 24.04 — они подтягиваются через `${python3:Depends}` / pybuild из
`pyproject.toml` при сборке `.deb`. PySide6 — системный `python3-pyside6.*`.

## Каталоги (ТЗ §8)

| Назначение | Путь |
|---|---|
| Программа | `/usr/lib/python3/dist-packages/` (pybuild) + `/usr/bin/personnel-availability` |
| SQL-миграции | `site-packages/data/migrations/` (package data) |
| Данные пользователя | `~/.local/share/personnel-availability/` (`personnel.db`, keywrap) |
| Резервные копии | `~/.local/share/personnel-availability/backups/` |
| Файловые логи | `~/.local/share/personnel-availability/logs/` |
| Шаблоны отчётов | `~/.local/share/personnel-availability/templates/` |

Переопределение каталога данных: `$PERSONNEL_AVAILABILITY_DATA`.

Журнал действий пользователей и технические события по-прежнему хранятся в
зашифрованной БД; файловый лог — для диагностики запуска и необработанных
исключений (без секретов).

## Обновление

- `dpkg` обновляет только файлы в `/usr`; пользовательские данные не затрагиваются.
- При первом входе после обновления приложение создаёт `pre-upgrade-*` бэкап и
  применяет миграции; при сбое — откат (см. `services/upgrade.py`).

## Удаление

`postinst`/`postrm` **не удаляют** `~/.local/share/personnel-availability/` при
`remove`/`upgrade` — только файлы в `/usr`. Данные пользователя сохраняются.

## CI

Job `deb-build` в GitHub Actions выполняет `dpkg-buildpackage` на Ubuntu 24.04
и публикует `.deb` как artifact.
