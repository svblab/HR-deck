# Установка и обновление — краткая инструкция

Памятка для администратора. Подробности — [`deployment-guide.md`](deployment-guide.md),
авторитетный источник по пакету — [`packaging/README.md`](../../packaging/README.md).

---

## Установка (Ubuntu 24.04 / Debian)

```bash
sudo dpkg -i dist/personnel-availability_*.deb
sudo apt-get install -f
```

Запуск: меню **«Журнал доступности персонала»** или команда
`personnel-availability`.

**Первый запуск:** мастер создания учётной записи Администратора и **резервного
кода** — сохраните код offline ([`administrator-guide.md`](administrator-guide.md) §2).

---

## Данные пользователя

| Что | Где |
|---|---|
| База и ключи | `~/.local/share/personnel-availability/personnel.db` + `.keywrap` |
| Резервные копии | `…/backups/` |
| Шаблоны отчётов | `…/templates/` |
| Файловые логи | `…/logs/` |

Переопределение: `$PERSONNEL_AVAILABILITY_DATA`.

Удаление пакета (`apt remove`) **не удаляет** эти каталоги.

---

## Обновление

```bash
sudo dpkg -i dist/personnel-availability_<новая>_all.deb
```

- Файлы в `/opt` и `/usr` обновляются; домашний каталог **не трогается**.
- При первом входе после обновления приложение создаёт **pre-upgrade** бэкап и
  применяет миграции БД; при сбое — автооткат ([`maintenance-runbook.md`](maintenance-runbook.md) §5).

**Перед обновлением:** создайте ручную резервную копию через **⚙ → Создать копию…**.

---

## Если что-то пошло не так

| Симптом | Документ |
|---|---|
| Не запускается после установки | [`deployment-guide.md`](deployment-guide.md) §6 |
| Ошибка БД / повреждение данных | [`maintenance-runbook.md`](maintenance-runbook.md) §2–3 |
| Сбой миграции после обновления | [`maintenance-runbook.md`](maintenance-runbook.md) §5 |
| Забыт пароль Администратора | [`maintenance-runbook.md`](maintenance-runbook.md) §4 |
