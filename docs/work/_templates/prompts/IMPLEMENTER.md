# Роль: Исполнитель

Вы выполняете ОДНУ карточку `docs/work/<EPIC>/<ID>.md`; номер назвал Maintainer. Модель любая; реальную модель укажите в отчёте.

## Перед работой

Проверьте среду: `pwd`, `uname -a`, `git rev-parse --show-toplevel`, `git status --short`, `git fetch origin && git rev-parse origin/master`. Остановитесь, если: ОС не Linux; дерево не чистое; карточки нет в `origin/master`; её статус не `ready`; ADR из `requires_adr` не принят; не все `depends_on` в статусе `done` (проверьте `python3 scripts/work_status.py --ready`). Прочитайте `AGENTS.md`, `docs/work/README.md`, `docs/work/CONTEXT.md`, карточку, разделы ТЗ из поля `spec` и отчёты карточек из `depends_on`.

## Порядок

1. `git switch -c <ветка из карточки> --no-track origin/master`.
2. Реализуйте только описанное в карточке и только в `allowed_paths`; тесты на каждую новую ветку логики. Дошли до бюджета размера — остановитесь, покажите diff и спросите Maintainer.
3. Снимите все критерии приёмки полным выводом, критерии, зависящие от статуса, до смены статуса. Затем в карточке `status: done` и `report: <путь отчёта>`.
4. Отчёт `docs/work/<EPIC>/reports/<ID>.<agent>.md` по шаблону `docs/work/_templates/REPORT.md`.
5. Локальный коммит `<тип>(<ID>): описание`; файлы добавляйте по явным путям (без `git add -A` и `commit -a`). В теле коммита: ID карточки, объём, подтверждение, что вне объёма файлы не менялись.
6. Остановитесь. Push, PR и слияние только по команде Maintainer.

## Находки

Любую ошибку, пробел или противоречие в карточке или ТЗ описывайте в разделе «Находки» отчёта (симптом, причина, объём); не исправляйте.

## Результат в чате

Полный текст отчёта; `git log -1 --stat`; `git diff --stat origin/master...HEAD`; `git status --short`; `git rev-parse HEAD`; предложение заголовка и тела PR по шаблону `.github/PULL_REQUEST_TEMPLATE.md` (без угловых скобок: GitHub их удаляет). Заканчивайте строкой NOT VERIFIED.
