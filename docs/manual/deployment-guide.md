# Руководство по развёртыванию

Описывает **фактическую** поставку EPIC-015 (пакет `personnel-availability`).
Сверено с [`packaging/README.md`](../../packaging/README.md), `scripts/build-deb.sh`,
`services/upgrade.py`.

Установка рассчитана на **Debian/Ubuntu** (ADR-0001, ТЗ §8). Целевая проверка:
**Ubuntu 24.04 LTS**.

Краткая памятка для администратора — [`install-update-quick.md`](install-update-quick.md).

---

## 1. Сборка пакета (для maintainer)

На машине разработчика с `debhelper`, `dh-python`, Docker (для smoke):

```bash
git clone …/HR-deck.git && cd HR-deck
chmod +x scripts/build-deb.sh packaging/debian/*.sh
./scripts/build-deb.sh
# Артефакт: dist/personnel-availability_*.deb
```

Скрипт копирует `packaging/debian/` → `debian/` и вызывает `dpkg-buildpackage`.
При сборке создаётся приватный venv в `/opt/personnel-availability/venv` и
включается в `.deb` (`packaging/debian/install-venv.sh`).

---

## 2. Установка

```bash
sudo dpkg -i dist/personnel-availability_*.deb
sudo apt-get install -f   # если не хватило зависимостей
```

**Устанавливается в систему:**

| Компонент | Путь |
|---|---|
| Приложение (venv) | `/opt/personnel-availability/venv/` |
| CLI / ярлык | `/usr/bin/personnel-availability` |
| SQL-миграции | внутри venv: `…/site-packages/data/migrations/` |
| Ярлык меню | `/usr/share/applications/personnel-availability.desktop` |

Runtime-зависимости Qt/XCB — см. `Depends:` в `packaging/debian/control`.
Пользователю **не** нужен `pip install`.

**Не затрагивается** домашний каталог пользователя.

---

## 3. Каталоги данных пользователя

По умолчанию: `~/.local/share/personnel-availability/`

| Подкаталог / файл | Содержимое |
|---|---|
| `personnel.db` | Зашифрованная SQLCipher-БД |
| `personnel.db.keywrap` | Sidecar с обёртками мастер-ключа (ADR-0003) |
| `backups/` | Резервные копии (ручные, pre-restore, pre-upgrade) |
| `logs/` | Файловые логи приложения |
| `templates/` | Файлы версий пользовательских шаблонов |

Переопределение корня: переменная **`PERSONNEL_AVAILABILITY_DATA`**.

Журнал действий пользователей и технические события хранятся **внутри**
`personnel.db` (`user_action_log`, `technical_events`), не в отдельных
файлах.

---

## 4. Первый запуск

1. Запустите из меню **«Журнал доступности персонала»** или
   `personnel-availability`.
2. Если БД отсутствует — **Первичная настройка**:
   - логин и пароль Администратора;
   - **резервный код** (сохраните offline).
3. `BootstrapService` создаёт каталоги данных, БД, применяет миграции,
   записывает keywrap.

Подробнее — [`administrator-guide.md`](administrator-guide.md) §1–2.

---

## 5. Обновление версии

```bash
sudo dpkg -i dist/personnel-availability_<новая>_all.deb
```

- `dpkg` обновляет **только** файлы в `/usr` и `/opt`.
- Данные в `~/.local/share/personnel-availability/` **не удаляются**
  (`postinst`/`postrm` не трогают домашний каталог).

При **первом входе** после обновления (`ui/app.py`):

1. `UpgradeService.apply_pending()` проверяет новые SQL-миграции.
2. Если есть — создаётся **pre-upgrade** бэкап в `backups/`.
3. Миграции применяются через `apply_pending_migrations`.
4. При ошибке — **автооткат** live-файлов из pre-upgrade бэкапа; вход прерывается
   с сообщением.

Runbook при сбое миграции — [`maintenance-runbook.md`](maintenance-runbook.md) §5.

---

## 6. Проверка после установки (checklist)

- [ ] `personnel-availability` запускается без ошибок в терминале.
- [ ] Ярлык появился в меню приложений.
- [ ] Первичная настройка / вход работает.
- [ ] В `~/.local/share/personnel-availability/` появились `personnel.db`, `.keywrap`,
      каталоги `backups/`, `logs/`, `templates/`.
- [ ] После тестового обновления `.deb` данные сохранились.

Автоматическая проверка в CI: jobs `deb-build` и `deb-verify` (см.
`packaging/README.md`). Локально: `./scripts/verify-deb-install.sh` после сборки.

---

## 7. Ссылки

| Тема | Файл |
|---|---|
| Packaging | `packaging/README.md` |
| Пути данных | `src/data/paths.py` |
| Миграции | `src/data/migrations.py` |
| Безопасное обновление | `src/services/upgrade.py` |
| Точка входа | `src/ui/app.py` |
