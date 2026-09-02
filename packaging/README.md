# Packaging (EPIC-015)

Сборка `.deb`, ярлык в меню и раздельные каталоги данных.

Ожидаемый пакет: `personnel-availability`.

**Целевой релиз для проверки:** Ubuntu 24.04 LTS.

## Сборка (Linux)

```bash
chmod +x scripts/build-deb.sh packaging/debian/*.sh
./scripts/build-deb.sh
# Артефакт: dist/personnel-availability_*.deb
```

## Зависимости Python (vendored venv)

Ubuntu 24.04 **не** поставляет `python3-pyside6*` и `sqlcipher3` в apt. Пакет
собирает приватный virtualenv в `/opt/personnel-availability/venv` на этапе
`dpkg-buildpackage` (`pip install` wheel + зависимости из `pyproject.toml`) и
включает его в `.deb`. При установке пользователю **не** нужен `pip install`.

`dh_python3` `${python3:Depends}` **не** используется для runtime — он только
сопоставляет имена PyPI с уже существующими deb-пакетами и не умеет vendoring.

Системные runtime-зависимости (Qt/EGL для offscreen/GUI): `libegl1`,
`libxkbcommon0`, `libgl1`, `libdbus-1-3`, `fonts-dejavu-core` и др. — см.
`packaging/debian/control`.

## Каталоги (ТЗ §8)

| Назначение | Путь |
|---|---|
| Программа | `/opt/personnel-availability/venv/` + `/usr/bin/personnel-availability` |
| SQL-миграции | `venv/.../site-packages/data/migrations/` (package data) |
| Данные пользователя | `~/.local/share/personnel-availability/` (`personnel.db`, keywrap) |
| Резервные копии | `~/.local/share/personnel-availability/backups/` |
| Файловые логи | `~/.local/share/personnel-availability/logs/` |
| Шаблоны отчётов | `~/.local/share/personnel-availability/templates/` |

Переопределение каталога данных: `$PERSONNEL_AVAILABILITY_DATA`.

## Обновление

- `dpkg` обновляет только файлы в `/usr` и `/opt`; пользовательские данные не затрагиваются.
- При первом входе после обновления приложение создаёт `pre-upgrade-*` бэкап и
  применяет миграции; при сбое — откат (см. `services/upgrade.py`).

## Удаление

`postinst`/`postrm` **не удаляют** `~/.local/share/personnel-availability/` при
`remove`/`upgrade`.

## CI

- Job `deb-build`: `dpkg-buildpackage` (артефакт `.deb`).
- Job `deb-verify`: чистый `ubuntu:24.04` контейнер, `apt-get install` артефакта,
  `scripts/verify-deb-smoke.sh` (shebang, импорты, Qt offscreen).

Локально: `./scripts/build-deb.sh` затем `./scripts/verify-deb-install.sh`
(docker/podman + `verify-deb-smoke.sh`).
