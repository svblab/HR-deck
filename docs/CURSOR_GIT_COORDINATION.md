# Cursor Git Coordination Protocol

Дополнение к [`ANCHOR_PROTOCOL.md`](ANCHOR_PROTOCOL.md). Тот документ остаётся
**авторитетным** для именования веток, diff-first, ADR-триггеров, тестов и
Definition of Done. Этот протокол закрывает повторяющийся класс ошибок:
**несинхронизированное состояние Git** между Cursor, человеком на GitHub и
LLM-ревьюером.

Постоянное правило Cursor: [`.cursor/rules/git-coordination.mdc`](../.cursor/rules/git-coordination.mdc).

---

## Purpose

Cursor не должен выводить состояние репозитория из истории чата или локальных
веток. Единственный надёжный источник — **удалённые refs после `git fetch`**.

Цель: после каждой сессии остаётся **корректное, воспроизводимое, аудируемое**
состояние Git, понятное следующему человеку, Cursor и LLM.

---

## Actors and Responsibilities

| Actor | Ответственность |
|-------|-----------------|
| **Cursor** | Реализация, тесты, коммиты, push feature-ветки, PR, отчёт о Git-состоянии |
| **Human** | Merge PR на GitHub, разрешение конфликтов, rebase/правки вне Cursor |
| **LLM reviewer** | Ревью diff, запрос правок, решение о готовности к merge |

Cursor **не мержит PR** по умолчанию. Остановка — `PR READY`, не «merged».

---

## Source of Truth

```text
origin/master
```

— каноническая интеграционная ветка; защищённая ветка репозитория —
`master` (см. также [`ANCHOR_PROTOCOL.md`](ANCHOR_PROTOCOL.md) §1).

Локальный `master` — **рабочая копия**, которая часто отстаёт после merge
человеком на GitHub. Это не обязательно «проблема репозитория».

Перед любым решением о ветке, PR или синхронизации:

```bash
git fetch --all --prune
git status --short --branch
git branch -vv
git rev-parse master
git rev-parse origin/master
```

---

## Repository State Model

Каждая задача находится ровно в одном из состояний:

### WORKING

- Выделенная feature/fix/docs-ветка
- Зафиксирован base SHA от `origin/master`
- Понятное состояние working tree
- Пока **нет** заявления о готовности PR

### PR READY

- Ветка запушена, PR существует
- Diff просмотрен, посторонних изменений нет
- DoD из `ANCHOR_PROTOCOL.md` §7 выполнен
- CI/тесты проверены
- LLM может ревьюить

**Не означает merged.**

### MERGED

- Только после проверки, что **содержимое** задачи присутствует в
  `origin/master`
- При squash-merge исходный SHA PR-ветки может **не** быть предком
  `origin/master` — проверять diff/content, не только ancestry

---

## Synchronization Rules

Три независимых «часов»:

```text
локальный checkout Cursor
действия человека на GitHub
понимание LLM из чата
```

Они **не синхронизируются автоматически**.

После сообщения человека «смержил» или после любой паузы, когда GitHub мог
измениться:

```bash
git fetch --all --prune
git log --oneline --decorate --graph origin/master -20
```

Убедиться, что ожидаемое содержимое в `origin/master`, затем при продолжении
работы:

```bash
git switch master
git pull --ff-only origin master
```

Только если working tree безопасно обновлять.

---

## Branch Rules

Именование — строго по [`ANCHOR_PROTOCOL.md`](ANCHOR_PROTOCOL.md) §2:

- `epic/EPIC-0NN-…`
- `fix/…`
- `docs/…` / `spike/…` по смыслу задачи

Запрещено вести разработку на `master` (кроме явно авторизованных
repo-level операций).

Новая ветка — от **свежего** `origin/master`, не от устаревшего локального
`master`.

---

## Diff-First Rules

Перед реализацией — зафиксировать base и baseline diff:

```bash
git diff --stat origin/master...HEAD
git diff origin/master...HEAD
```

Перед каждым push — повторить плюс:

```bash
git status
git diff --check
```

Расследовать: посторонние файлы, revert, EOL-only diff, generated artifacts,
наследие от старой base-ветки.

Порог «>300 строк → сначала структура» — по [`ANCHOR_PROTOCOL.md`](ANCHOR_PROTOCOL.md) §5.

---

## PR and Merge Rules

Канонический поток:

```text
VERIFY → DIFF → ACT → TEST → COMMIT → PUSH → PR READY
  → LLM REVIEW → CHANGES REQUESTED → VERIFY (повтор)
  → APPROVED → HUMAN MERGE → VERIFY origin/master → MERGED
```

Cursor **не** выполняет `git merge` / `git rebase master` / `git push origin
master` как «завершение PR», если явно не поручено.

PR не считается merged, если:

- LLM сказал «ready»;
- Cursor создал PR;
- CI зелёный;
- человек *намеревался* смержить.

---

## Human Merge Handoff

Нормальная точка остановки Cursor:

```text
feature branch pushed
PR updated
CI/tests checked
State: PR READY
Next action: human merge on GitHub
```

После merge человек сообщает; Cursor **верифицирует** remote, не продолжает со
старого локального состояния.

---

## Post-Merge Synchronization

```bash
git fetch --all --prune
# content verification against origin/master
git switch master
git pull --ff-only origin master
```

Следующая feature-ветка — только после ff-only обновления `master`.

---

## Destructive Git Operations

Без **явного** разрешения не выполнять:

```text
git reset --hard
git clean -fd
git push --force
git push --force-with-lease
git branch -D
git rebase
```

### `[gone]` upstream ≠ безопасно удалять

Upstream `[gone]` означает, что remote ref удалён. Локальная ветка может
содержать уникальные или неслитые коммиты. Перед удалением:

```bash
git log origin/master..<branch> --oneline
git diff origin/master...<branch> --stat
```

### Untracked files

Не удалять, не `git clean`, не перезаписывать untracked файлы без
авторизации — они могут быть намеренной незакоммиченной работой.

---

## Suspicious Repository State

**STOP и отчёт**, без автоматического «лечения», если:

- `origin/master` стал orphan/unrelated root;
- исчезла ожидаемая история или файлы;
- merge/revert затронул несвязанные EPIC/ADR;
- неожиданный base PR-ветки;
- обнаружен force-push;
- `origin/master` «откатился» назад.

Шаблон отчёта — в `.cursor/rules/git-coordination.mdc`.

---

## ADR Integration

ADR-триггеры — [`ANCHOR_PROTOCOL.md`](ANCHOR_PROTOCOL.md) §4. Этот протокол
координации Git **не заменяет** ADR-процесс.

Добавление workflow-документации само по себе ADR **не требует**, если не
меняется архитектура, контракты данных, packaging/release или cross-EPIC
решения.

---

## Definition of Done

DoD задачи в EPIC — по [`ANCHOR_PROTOCOL.md`](ANCHOR_PROTOCOL.md) §7.

Дополнительно для Git-координации:

- [ ] `git fetch` выполнен, remote refs проверены
- [ ] ветка от verified `origin/master`
- [ ] diff без посторонних изменений
- [ ] HEAD SHA записан в отчёте
- [ ] состояние явно: WORKING / PR READY / MERGED
- [ ] merge verified content-first, если заявлен MERGED

---

## Required Final Report

Формат обязателен для завершённой PR-работы (см. также rule file):

```text
## PR Status
PR: #<number>
Branch: <branch>
Base: origin/master @ <SHA>
HEAD: <SHA>
State: WORKING | PR READY | MERGED

## Diff
Files changed: <N>
Insertions: <N>
Deletions: <N>
Unrelated changes: none / <details>

## Tests
- <command> — PASS/FAIL
- CI — PASS/FAIL/PENDING

## Architecture
ADR impact: NONE / UPDATED / NEW ADR REQUIRED
EPIC impact: <list>

## DoD
- [x] ...

## Git Coordination
Remote checked at: origin/master @ <SHA>
Local master: <SHA>
Merge verified: YES / NO / NOT YET

## Next action
<exact next step>
```

Не писать «Done» без указания Git state и merge verification status.
