# Packaging (заготовка EPIC-001)

Полная сборка `.deb`, ярлык в меню и раздельные каталоги данных —
в **EPIC-015**. Здесь только каркас `debian/` для будущей сборки.

Ожидаемый пакет: `personnel-availability`.

Сборка (позже, на Linux):

```bash
# после заполнения EPIC-015
dpkg-buildpackage -us -uc -b
```

Каталоги установки (по ТЗ §8 / ANCHOR_CORE):

| Назначение | Путь (ориентир) |
|---|---|
| Программа | `/usr/share/personnel-availability/` + `/usr/bin/personnel-availability` |
| Данные пользователя | `~/.local/share/personnel-availability/` |
| Резервные копии | `~/.local/share/personnel-availability/backups/` |
| Логи | `~/.local/share/personnel-availability/logs/` |
| Шаблоны отчётов | `~/.local/share/personnel-availability/templates/` |
