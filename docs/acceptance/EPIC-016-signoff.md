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
| 5 | Backup create + restore | ☐ | — | — | yes | _pending_ |
| 6 | `.deb` upgrade on test copy | ☐ | — | — | CI deb-verify | _pending_ |

---

## 5. Packaging / offline (TESTING §2.7, EPIC-015)

| Check | Evidence |
|---|---|
| `deb-build` job | `.github/workflows/ci.yml` |
| Docker install smoke | `scripts/verify-deb-smoke.sh` |
| Offline `--network none` | CI `deb-verify` + `test_packaging_smoke.py` |
| Local maintainer path | `packaging/README.md`, `docs/manual/deployment-guide.md` |

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
