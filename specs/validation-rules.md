# Правила автопроверки и отчёт агента

Префикс требований: `SPEC-RULES`. Код: `src/app/validation/rules.py` (V-01…V-27), `src/app/validation/report.py`, `src/app/validation/ngrams.py`. Подробности — [docs/validation.md](../docs/validation.md).

## Назначение

27 правил — чистые функции над `ProgramDoc`: 20 правил объединены в 10 блокирующих проверок, 7 дают только предупреждения; 23 реализованы кодом, 4 смысловых (V-21, V-22, V-26, V-27) — эвристиками, которые уточняет судья. Отчёт агента сводит статусы правил, блокирующие проверки, матрицу «РО × средство», действия методиста, предложения по пунктам «!» и допущения. От отчёта зависят утверждение каркаса, назначение экспертов, отправка на утверждение и индекс готовности.

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-RULES-01 | THE SYSTEM SHALL проверять программу 27 правилами V-01…V-27, из которых V-21, V-22, V-26, V-27 имеют вид `llm`, остальные — `code`. | FR-32 | `test_spec_rules.py::test_27_rules_kinds` |
| SPEC-RULES-02 | WHEN проверяется каркас, THE SYSTEM SHALL выполнять только 15 правил этапа `skeleton` (V-01…V-08, V-10, V-12, V-13, V-15, V-21, V-22, V-27); WHEN проверяется комплект — все 27. | FR-32 | `test_spec_rules.py::test_stage_rule_sets` |
| SPEC-RULES-03 | IF у правила нет блокирующей проверки, THEN THE SYSTEM SHALL понижать его `fail` до `warn`; IF правило бросило исключение, THEN THE SYSTEM SHALL дать ему `warn` «Правило не выполнено», не роняя отчёт. | код | `test_spec_rules.py::test_fail_downgraded_and_exception_isolated` |
| SPEC-RULES-04 | THE SYSTEM SHALL считать блокирующую проверку пройденной, если ни одно её правило не имеет статуса `fail`, и выдавать счёт из 10 на этапе комплекта и из 5 на этапе каркаса. | FR-33, FR-35 | `test_core.py::test_open_cases_auto`, `test_access.py::test_auto_async_returns_202_and_job_result` |
| SPEC-RULES-05 | IF суммы часов тем, строк, модулей или итог с ИА не сходятся с планом и объёмом (V-01…V-04), THEN THE SYSTEM SHALL выдать `fail` проверки 1. | FR-15, FR-32 | `test_core.py::test_open_cases_auto` |
| SPEC-RULES-06 | IF контактная работа в тексте раздела объёма не равна ЛК + ПР + ЛБ плана (V-05), у стажировки есть аудиторные часы (V-06) или практика ниже минимума запроса / 40 % аудиторных для ДПП ПК (V-07), THEN THE SYSTEM SHALL выдать `fail` проверки 1. | FR-16 | `test_spec_rules.py::test_v05_v06_v07_hours_rules` |
| SPEC-RULES-07 | IF пуст обязательный раздел шаблона или элемент каркаса (V-08) либо нет материалов из запроса (V-09), THEN THE SYSTEM SHALL выдать `fail` проверки 2. | FR-25 | `test_spec_rules.py::test_v08_v09_completeness` |
| SPEC-RULES-08 | WHILE конфликт календаря не решён выбором варианта или нагрузка выше ограничения запроса (V-10), THE SYSTEM SHALL выдавать `fail` проверки 3. | FR-18 | `test_spec_rules.py::test_v10_calendar` |
| SPEC-RULES-09 | IF в реквизитах заполнены номер приказа, дата или ФИО (V-11), THEN THE SYSTEM SHALL выдать `fail` проверки 4. | FR-52, NFR-11 | `test_spec_rules.py::test_v11_human_fields` |
| SPEC-RULES-10 | IF РО не раскрыт ни в одной теме (V-12) или проверяется меньше чем двумя средствами (V-13), THEN THE SYSTEM SHALL выдать `fail` проверки 5. | FR-34, FR-45 | `test_spec_rules.py::test_v12_v13_coverage` |
| SPEC-RULES-11 | IF вопрос или задание не привязаны к существующему РО (V-14), THEN THE SYSTEM SHALL выдать `fail` проверки 6. | FR-45 | `test_spec_rules.py::test_v14_binding` |
| SPEC-RULES-12 | IF ПС или коды ТФ не из реестра, у ДООП есть ПС (V-15) или источник не найден в реестре и не помечен «не подтверждено» (V-16), THEN THE SYSTEM SHALL выдать `fail` проверки 7. | FR-07, FR-29 | `test_spec_rules.py::test_v15_v16_sources` |
| SPEC-RULES-13 | IF доля 8-грамм содержания, совпадающих с референсами, не меньше 5 % (V-17), THEN THE SYSTEM SHALL выдать `fail` проверки 8. | FR-04 | `test_spec_rules.py::test_v17_originality` |
| SPEC-RULES-14 | IF у задания нет критериев с баллами больше 0 (V-18) или ключ вопроса не указывает на существующий вариант либо варианты повторяются (V-19), THEN THE SYSTEM SHALL выдать `fail` проверки 9. | FR-26, FR-27 | `test_spec_rules.py::test_v18_v19_measurability` |
| SPEC-RULES-15 | WHEN порядок тем нарушает пререквизиты (V-21) или РО начинается с непроверяемого глагола «понимает», «знаком» и т. п. (V-22), THE SYSTEM SHALL выдать `warn` и предложение для решения по узлу. | FR-22 | `test_skeleton.py::test_decisions_per_node` |
| SPEC-RULES-16 | WHEN версии инструментов устарели (V-23), примеры кода падают (V-24), темы разных модулей почти совпадают (сходство > 0.85, V-25), доля кириллицы ниже 80 % (V-26) или обещания нереалистичны (V-27), THE SYSTEM SHALL выдавать только `warn`. | FR-32 | `test_spec_rules.py::test_warning_only_rules` |
| SPEC-RULES-17 | THE SYSTEM SHALL включать в отчёт правила, счёт блокирующих проверок, матрицу покрытия, до 20 действий методиста, предложения с признаком `decided` и допущения агента. | FR-33, FR-34 | `test_skeleton.py::test_decisions_per_node`, `test_skeleton.py::test_topic_hours_manual_and_assumptions` |
| SPEC-RULES-18 | THE SYSTEM SHALL строить матрицу «РО × средство оценивания»: на каркасе — по плановым средствам, на комплекте — по фактическим вопросам и заданиям. | FR-34 | `test_spec_rules.py::test_coverage_matrix_planned_and_actual` |
| SPEC-RULES-19 | THE SYSTEM SHALL считать оригинальность как долю 8-грамм текста (слова латиницы, кириллицы, цифры в нижнем регистре), встречающихся в референсе. | FR-04 | `test_spec_rules.py::test_originality_by_8grams` |
| SPEC-RULES-20 | WHEN формируется ответ автопрогона, THE SYSTEM SHALL отдавать `rules_passed` (правила не в `fail`), `rules_total`, `blocking_checks` вида `N/10` и `failed_rules`. | FR-62 | `test_core.py::test_open_cases_auto` |

## Вне области

- Уточнение смысловых правил моделью — [validation-judge.md](validation-judge.md).
- Исправление нарушений — [validation-repair.md](validation-repair.md).
- Запуск примеров кода — [validation-sandbox.md](validation-sandbox.md).
- V-20 на практике обеспечивается откатом правки в `workflow.edit` ([agent-workflow.md](agent-workflow.md)).
