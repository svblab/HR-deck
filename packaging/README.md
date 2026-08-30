# Packaging (EPIC-015)

Сборка `.deb`, ярлык в меню и раздельные каталоги данных.

Ожидаемый пакет: `personnel-availability`.

## Сборка (Linux)

```bash
./scripts/build-deb.sh
# или: dpkg-buildpackage -us -uc -b после копирования packaging/debian → debian/
```

## Каталоги (ТЗ §8)

| Назначение | Путь |
|---|---|
| Программа | `/usr/lib/python3/dist-packages/` (pybuild) + `/usr/bin/personnel-availability` |
| SQL-миграции | `/usr/share/personnel-availability/migrations/` |
| Данные пользователя | `~/.local/share/personnel-availability/` (`personnel.db`, keywrap) |
| Резервные копии | `~/.local/share/personnel-availability/backups/` |
| Шаблоны отчётов | `~/.local/share/personnel-availability/templates/` |

Переопределение каталога данных: `$PERSONNEL_AVAILABILITY_DATA`.

### «Логи» (разрешение Step 0)

Отдельного каталога `logs/` **нет**: журнал действий пользователей
(`user_action_log`) и технические события (`technical_events`, в т.ч. бэкап/
восстановление/обновление) хранятся **внутри зашифрованной** `personnel.db`.
Это покрывает требование ТЗ §8 о раздельном учёте «логов» как подотчётности,
без пустого каталога на диске. Ошибки до открытия БД показываются в GUI
(`QMessageBox`) или stderr (CLI upgrade path).

## Обновление

- `dpkg` обновляет только файлы в `/usr`; пользовательские данные не затрагиваются.
- При первом входе после обновления приложение создаёт pre-upgrade бэкап и
  применяет миграции; при сбое — откат из бэкапа (см. `services/upgrade.py`).

## CI

Полная сборка `.deb` в GitHub Actions не выполняется (нужен Debian build env и
системные зависимости PySide6/sqlcipher3). Smoke-тест проверяет наличие файлов
упаковки; релизная сборка — вручную на целевой Linux-системе.
