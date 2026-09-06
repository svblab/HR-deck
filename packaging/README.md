# Packaging (EPIC-015)

Сборка `.deb`, ярлык в меню и раздельные каталоги данных.

Ожидаемый пакет: `personnel-availability`.

**Целевой релиз для проверки:** Debian 12 (bookworm) или новее
(ADR-0001, дополнение 2026-09-06).

## Сборка (Linux)

Собирайте на **Debian 12** (или в `docker run … debian:12`), чтобы vendored
venv совпал с целевым Python 3.11. Сборка на Ubuntu 24.04 (Python 3.12) даёт
пакет, который не импортирует зависимости после установки на bookworm.

```bash
chmod +x scripts/build-deb.sh packaging/debian/*.sh
./scripts/build-deb.sh
# Артефакт: dist/personnel-availability_*.deb
```

## Зависимости Python (vendored venv)

Debian 12 **не** поставляет `python3-pyside6*` и `sqlcipher3` в apt. Пакет
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

- Job `deb-build`: Docker `debian:12` on the Ubuntu runner — builds the `.deb`
  with bookworm’s Python 3.11 so the vendored venv matches the deploy target
  (building on the runner’s Ubuntu Python 3.12 breaks install on Debian 12).
- Job `deb-verify`: Docker `debian:12` (preinstalled runner Docker),
  `apt-get install` артефакта, `verify-deb-smoke.sh`, затем тот же smoke в
  образе с `--network none` (офлайн-старт без сети).

Локально: предпочтительно собирать на Debian 12 (или
`docker run … debian:12 ./scripts/build-deb.sh`), затем
`./scripts/verify-deb-install.sh` (docker/podman + smoke + `--network none`).

Папка для передачи тестировщику (`.deb` + checksum + инструкции):  
`./scripts/make-test-bundle.sh` → `dist/test-bundle-<version>/`.
