# Установка и обновление — краткая инструкция

Памятка для администратора. Подробности — [`deployment-guide.md`](deployment-guide.md),
авторитетный источник по пакету — [`packaging/README.md`](../../packaging/README.md).

---

## 0. Перед установкой — проверка системы

Выполните эти шаги **до** `dpkg -i`, на ноутбуке, куда ставите программу.
Цель: понять, подойдёт ли машина и нужна ли сеть при установке.

Список runtime-зависимостей ниже взят из поля `Depends:` файла
`packaging/debian/control` (и совпадает с `dpkg-deb --info` у собранного
`.deb`). Целевая платформа — **Debian 12 (bookworm) или новее (amd64)** по
ADR-0001 (дополнение 2026-09-06) / ТЗ §8.

### 0.1. Версия Debian

```bash
. /etc/os-release
echo "$NAME $VERSION_ID"
```

**ОК:** имя содержит `Debian`, `VERSION_ID` **≥ 12** (например `12`).

Если другая версия Debian (< 12) или другой дистрибутив (Ubuntu, Mint и т.п.):
пакет **проверялся** только на Debian 12. Можно пробовать на свой риск или
взять машину/ВМ с Debian 12+.

### 0.2. Архитектура

```bash
uname -m
```

**ОК:** `x86_64` (это amd64 — архитектура пакета в `control`).

Если вывод другой (например, `aarch64`) — этот `.deb` **не** подойдёт.

### 0.3. Свободное место на диске

Узнайте размер установки из самого файла пакета (поле `Installed-Size` —
в килобайтах):

```bash
dpkg-deb --info personnel-availability_*.deb | grep Installed-Size
df -h /
```

Для выпуска `0.1.0-1` при сборке на Debian 12 было:
**Installed-Size ≈ 752812 КБ (~735 МБ)** плюс сам файл `.deb` ≈ **192 МБ**.
С запасом на распаковку и данные пользователя держите **не меньше ~1,5 ГБ**
свободно на `/` (операционная рекомендация; CI это число не измеряет).

**ОК:** `df -h /` показывает достаточно свободного места (колонка `Avail`).

### 0.4. Уже ли стоят системные библиотеки

Проверьте каждый пакет из `Depends:` (имена — как в `packaging/debian/control`):

```bash
for pkg in python3 libegl1 libxkbcommon0 libgl1 libdbus-1-3 \
  libfontconfig1 libfreetype6 libglib2.0-0 libxcb-xinerama0 libxcb-cursor0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
  libxcb-shape0 fonts-dejavu-core
do
  echo -n "$pkg: "
  if dpkg -s "$pkg" >/dev/null 2>&1; then echo OK; else echo MISSING; fi
done
```

**ОК:** у всех строк `OK`.  
`MISSING` значит при `apt-get install -f` apt попытается **скачать** пакет
из интернета (если сеть есть).

Имена пакетов из `Depends:` проверены на Debian 12 (`apt-cache policy` в
образе `debian:12`): все присутствуют под теми же именами. На bookworm
переходных имён `*t64` для этих пакетов нет.

### 0.5. Есть ли интернет и что делать дальше

```bash
ping -c 1 1.1.1.1
# или: curl -I --max-time 5 https://deb.debian.org/
```

| Сеть | Результат §0.4 | Действие |
|---|---|---|
| Есть | любые | Обычная установка (§ «Установка»): `dpkg -i` + `apt-get install -f`. |
| Нет | все `OK` | Можно ставить **полностью офлайн**: достаточно `sudo dpkg -i …deb` (без `apt-get install -f`). |
| Нет | есть `MISSING` | Сначала на **другой** машине с Debian 12 (bookworm) amd64 **и** интернетом скачайте недостающие `.deb`, скопируйте на тот же носитель, что и основной пакет, затем на целевом ноутбуке установите все сразу (см. ниже). |

**Предзагрузка зависимостей** (рекомендуемая процедура для офлайн-ноутбука;
**не** покрыта текущими автотестами CI — проверяется вручную):

На машине с сетью (та же Debian 12 bookworm amd64):

```bash
mkdir -p ~/pa-deps && cd ~/pa-deps
# Перечислите только то, что было MISSING в §0.4, например:
sudo apt-get update
apt-get download python3 libegl1 libxkbcommon0 libgl1 libdbus-1-3 \
  libfontconfig1 libfreetype6 libglib2.0-0 libxcb-xinerama0 libxcb-cursor0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
  libxcb-shape0 fonts-dejavu-core
# При необходимости apt может предложить дополнительные пакеты —
# их тоже нужно скачать (apt-get download …).
```

Скопируйте папку `pa-deps` и файл `personnel-availability_*.deb` на флешку.
На целевом ноутбуке **без сети**:

```bash
cd /path/to/media   # где лежат .deb зависимостей и основной пакет
sudo dpkg -i *.deb
```

Если `dpkg` всё ещё ругается на зависимости — какого-то `.deb` не хватило;
докачайте его на машине с сетью и повторите.

---

## Установка (Debian 12+ / семейство Debian)

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
sudo dpkg -i dist/personnel-availability_<новая>_amd64.deb
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
