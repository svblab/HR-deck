# EPIC-016 — приёмочная трассировка и чек-листы

Документ фиксирует результаты финальной приёмки (EPIC-016). Матрица
соответствия тестам — `docs/TESTING.md` §2; здесь — **статус прогона** и
ручные ворота.

**База прогона:** `origin/master` @ `4aeda4e` (после merge EPIC-017 closeout #32).

---

## 1. Матрица приёмки (TESTING §2 → evidence)

| Ref | Критерий | Автотест / артеfact | Ручная проверка | Результат |
|---|---|---|---|---|
| 2.1 | Шифрование, роли, recovery | `test_encryption.py`, `test_auth_rbac.py`, `test_permissions_matrix.py` | — | ✅ automated |
| 2.2 | Журнал действий | `test_user_action_log.py`, `test_repositories_append_only.py` | — | ✅ automated |
| 2.3 | 5 стандартных отчётов | `test_standard_reports.py` | — | ✅ automated |
| 2.4 | Шаблоны Excel/PDF | `test_template_library*.py`, `test_template_samples.py` | — | ✅ automated |
| 2.5 | Документация шаблонов (non-author) | — | **§3 ниже — PASS (2026-09-05)** | ✅ human gate |
| 2.6 | Расширяемость, архив, импорт | `test_employee_*`, `test_roster.py`, … | UI чек-лист §4 | 🟡 partial auto |
| 2.7 | Бэкап, миграции, аварийное завершение | `test_backup_restore.py`, `test_safe_upgrade.py`, `test_crash_recovery_acceptance.py` | offline §5 | ✅ automated (+ offline CI) |
| 2.8 | Производительность ~400 сотр. | `generate_perf_dataset.py`, `test_perf_acceptance.py` | качественная оценка §2 | ✅ automated smoke |

---

## 2. Производительность (TESTING §2.8)

**Методология**

- Генератор: `tests/fixtures/generate_perf_dataset.py` (`seed_perf_dataset`, CLI `--count 400`).
- Синтетическая компания «Филиал Нагрузка (тест)», 400 сотрудников, ~75% с историей статусов.
- Прогон: `pytest tests/integration/test_perf_acceptance.py -q` (offscreen, локально/CI).
- Критерий ТЗ: **качественный** («без заметного зависания»); тесты используют
  generous upper bounds только как сторожевые пороги против регрессии-hang, не
  как SLA.

**Workflows covered**

| Workflow | Test |
|---|---|
| Поиск по ФИО | `test_perf_search_roster_on_large_dataset` |
| Главный экран / roster | `test_perf_search_roster_on_large_dataset` |
| Смена статуса | `test_perf_status_change_and_standard_report` |
| Стандартный отчёт | `test_perf_status_change_and_standard_report` |
| Шаблонный отчёт | `test_perf_template_report_on_large_dataset` |
| Создание карточки | `test_perf_create_employee_on_large_dataset` |

---

## 3. Template-document manual acceptance (TESTING §2.5)

**Gate:** человек, **не автор** движка шаблонов (`reports/excel_template.py`,
`reports/pdf_template.py`).

**Instructions for reviewer**

1. Прочитать только: `docs/report-templates-guide.md`, `templates_samples/`.
2. Без обращения к разработчику подготовить **новый** Excel-шаблон с:
   - скалярами `{{заголовок}}`, `{{период_с}}`, `{{период_по}}`;
   - блоком `{{#ROW}}` с колонками ФИО/должность;
   - только маркерами из каталога §1 guide.
3. Загрузить через UI **Шаблоны → Загрузить**; убедиться, что валидация проходит.
4. Сформировать отчёт; зафиксировать результат.

**Sign-off (fill by human reviewer)**

| Field | Value |
|---|---|
| Reviewer (non-author) | Петров Семён Романович |
| Date | 2026-09-05 |
| Outcome | ☑ PASS ☐ FAIL |
| Notes | Шаблон собран самостоятельно по `docs/report-templates-guide.md` без обращения к разработчику, валидация при загрузке прошла без ошибок. Отчёт сформирован; скалярные и `{{#ROW}}`-маркеры вышли пустыми — соответствует §8 гайда (текущая версия генерирует с `values={}`, диалога ввода данных нет). Отдельно замечено: в одной ячейке маркер `{{должность}` написан с опечаткой (одна закрывающая скобка вместо двух) — движок (`MARKER_RE` требует ровно `{{…}}`) не распознал его ни как известный, ни как unknown-маркер, поэтому валидация его пропустила молча, а в отчёте он остался как есть. Это не помешало пройти гейт (баг относится к движку/UX валидации, не к качеству документации); тикет: [#36](https://github.com/svblab/HR-deck/issues/36). |

---

## 4. UI acceptance checklist (TESTING §5.2)

Automated partial coverage: `test_main_window_smoke.py`, dialog unit tests.

**Manual checklist (three roles)**

| # | Scenario | Admin | HR | Observer | Auto | Manual sign-off |
|---|---|:---:|:---:|:---:|:---:|:---:|
| 1 | Login / unlock | ☐ | ☐ | ☐ | partial | _pending_ |
| 2 | Search → card → status cycle | ☐ | ☐ | view only | partial | _pending_ |
| 3 | Standard report Excel+PDF | ☐ | ☐ | ☐ | yes | _pending_ |
| 4 | Template report generate | ☐ | ☐ | ☐ | yes | _pending_ |
| 5 | Backup create + restore | ☑ | — | — | yes | PASS (2026-09-05; training DB) |
| 6 | `.deb` upgrade on test copy | ☑ | — | — | CI deb-verify | PASS (2026-09-05; путь b) |

**Item 5 evidence:** dialog `BackupDialog` (⚙) delegates to `BackupService` / `MainWindow._replace_connection` (reconnect without restart). On training DB (`personnel-availability-training`, admin/`Training-1`): create → `personnel-*.db` + `.keywrap` + integrity verify; change employee #1 status office→remote; restore → new `pre-restore-personnel-*.db` (+ keywrap), status rolled back to office. Also `pytest tests/integration/test_backup_restore.py tests/unit/test_backup_dialog.py` — all passed (incl. round-trip, pre-restore, UI create/restore with mocked file dialogs).

**Item 6 evidence (path b — Windows host, no local Ubuntu upgrade):** packaging/offline closed by CI on `master` @ `e4e3b04` — [run 33956982879](https://github.com/svblab/HR-deck/actions/runs/33956982879): `deb-build` + `deb-verify` (install smoke on `ubuntu:24.04` and offline `--network none`) both success. Upgrade/data path: `pytest tests/integration/test_safe_upgrade.py` — 3 passed (pre-upgrade `pre-upgrade-*` on non-empty DB, data preserved, rollback). Full dual-`.deb` install on a training DB copy (path a) not required for this gate.

---

## 5. Packaging / offline (TESTING §2.7, EPIC-015)

| Check | Evidence |
|---|---|
| `deb-build` job | CI run above — success |
| Docker install smoke | CI `deb-verify` step «Install and smoke-verify on clean Ubuntu 24.04» |
| Offline `--network none` | CI `deb-verify` step «Offline smoke (--network none)» |
| Local maintainer path | `packaging/README.md`, `docs/manual/deployment-guide.md` |
| pre-upgrade + migrations | `tests/integration/test_safe_upgrade.py` (acceptance) |

---

## 6. Regression baseline (TESTING §5)

| Step | Command | Expected |
|---|---|---|
| Full suite | `pytest -q` | all pass |
| Acceptance subset | `pytest -m acceptance -q` | all pass |
| Lint | `ruff check src tests` | pass |

Record actual counts in PR verification section.

---

## 7. EPIC-016 closure status

| Item | Status |
|---|---|
| Automated acceptance scope | ✅ in PR |
| Performance dataset + tests | ✅ in PR |
| Crash/recovery gap test | ✅ in PR |
| Template non-author gate | ✅ PASS (2026-09-05; Петров Семён Романович) |
| UI manual checklist | ⏸ **PENDING HUMAN** |
| ROADMAP EPIC-016 row | ⏸ separate closeout after human gates |

**EPIC-017 → EPIC-016 hard dependency:** unchanged on master (PR #30).
