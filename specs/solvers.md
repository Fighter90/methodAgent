# Солверы часов и календаря

Префикс требований: `SPEC-SOLVER`. Код: `src/app/solver/hours.py`, `src/app/solver/calendar.py`. Подробности — [docs/solvers.md](../docs/solvers.md).

## Назначение

Часы программы и календарный график считает детерминированный код, а не модель: модель даёт только веса и доли. Солвер часов раскладывает объём по модулям, видам работы и темам методом наибольших остатков так, что суммы сходятся на всех уровнях; солвер календаря строит график по дням или занятиям и при несовместимости объёма, нагрузки и срока выдаёт конфликт с тремя вариантами.

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-SOLVER-01 | WHEN целое `total` делится по положительным весам методом наибольших остатков, THE SYSTEM SHALL вернуть неотрицательные целые части с суммой ровно `total`. | FR-15 | `test_core.py::test_largest_remainder_sums` |
| SPEC-SOLVER-02 | THE SYSTEM SHALL давать одинаковый результат на одинаковом входе; при равных остатках единица достаётся большему весу, затем меньшему номеру. | NFR-09 | `test_spec_solvers.py::test_largest_remainder_deterministic`, `test_spec_solvers.py::test_largest_remainder_tie_break` |
| SPEC-SOLVER-03 | THE SYSTEM SHALL округлять доли арифметически (`floor(x + 0.5)`), а не банковским округлением. | код | `test_spec_solvers.py::test_round_half_up_not_bankers` |
| SPEC-SOLVER-04 | WHEN солвер раскладывает объём, THE SYSTEM SHALL обеспечить, что сумма часов модулей и итоговой аттестации равна объёму программы; IF объём не положителен или модулей нет, THEN THE SYSTEM SHALL отказать (`ValueError`). | FR-15 | `test_core.py::test_open_cases_auto`, `test_extras.py::test_adapt_keeps_competencies_and_resolves_hours`, `test_tz_compliance.py::test_solver_property_all_levels` |
| SPEC-SOLVER-05 | THE SYSTEM SHALL обеспечивать в каждой строке модуля ЛК + ПР + ЛБ + СРС = «Всего», закрывая строку практикой. | FR-16 | `test_core.py::test_open_cases_auto`, `test_tz_compliance.py::test_solver_property_all_levels` |
| SPEC-SOLVER-06 | THE SYSTEM SHALL делить часы модуля по темам так, что сумма тем равна модулю по каждому виду работы и итогу, а каждая тема получает не меньше 1 ч; IF тем больше, чем часов, THEN THE SYSTEM SHALL отбросить лишние темы с заметкой. | FR-16 | `test_core.py::test_open_cases_auto`, `test_tz_compliance.py::test_solver_property_all_levels` |
| SPEC-SOLVER-07 | WHILE программа — стажировка, THE SYSTEM SHALL относить все часы модулей к СРС, а ЛК, ПР и ЛБ делать равными 0. | FR-06 | `test_extras.py::test_change_template_before_approval`, `test_tz_compliance.py::test_solver_property_all_levels` |
| SPEC-SOLVER-08 | WHEN задан минимум практики, THE SYSTEM SHALL уменьшать доли ЛК и СРС до его выполнения; IF минимум не набирается, THEN THE SYSTEM SHALL оставить заметку методисту. | FR-16 | `test_spec_solvers.py::test_min_practice_reduces_lk_and_srs`, `test_spec_solvers.py::test_min_practice_unreachable_note` |
| SPEC-SOLVER-09 | THE SYSTEM SHALL принимать от каркаса только веса модулей и тем, доли ЛК и СРС и часы ЛБ; часы модель не задаёт. | FR-15 | `test_spec_solvers.py::test_solver_takes_only_weights_and_shares` |
| SPEC-SOLVER-10 | WHEN заданы занятия «по H ч N раз в неделю», THE SYSTEM SHALL планировать `ceil(объём / H)` занятий и `ceil(занятий / N)` недель. | FR-18 | `test_spec_solvers.py::test_calendar_by_sessions` |
| SPEC-SOLVER-11 | WHEN график строится по дням, THE SYSTEM SHALL брать нагрузку в день из запроса (иначе вычислять её по сроку или 6 ч) и планировать `ceil(объём / нагрузка)` рабочих дней. | FR-18 | `test_spec_solvers.py::test_calendar_by_days` |
| SPEC-SOLVER-12 | IF плановое число недель больше `ceil(срок + 0.25)`, THEN THE SYSTEM SHALL зафиксировать конфликт с объяснением и предложить варианты `extend`, `six_days`, `raise_load`. | FR-18 | `test_spec_solvers.py::test_calendar_conflict_and_options` |
| SPEC-SOLVER-13 | WHEN выбран вариант разрешения конфликта, THE SYSTEM SHALL пересчитать рабочие дни, недели, недельную нагрузку и расписание. | FR-18 | `test_spec_solvers.py::test_calendar_apply_option_recomputes` |
| SPEC-SOLVER-14 | THE SYSTEM SHALL строить расписание по неделям так, что сумма часов недель равна объёму программы, а в каждой неделе ЛК + ПР + ЛБ + СРС + ИА равны часам недели. | FR-18 | `test_skeleton.py::test_calendar_kinds_and_lecture_plans` |
| SPEC-SOLVER-15 | WHEN методист меняет часы, THE SYSTEM SHALL пересчитывать план за доли секунды без вызова модели. | NFR-05 | `test_spec_solvers.py::test_recompute_is_fast_and_offline` |
| SPEC-SOLVER-16 | IF рабочий график требует больше рабочих дней, чем помещается в запрошенный срок (`floor(срок × дней в неделю)`), THEN THE SYSTEM SHALL зафиксировать конфликт и предложить варианты, не округляя срок в пользу прохождения проверки (допуск `ceil(срок + 0.25)` запрещён). | FR-18, аудит 19.10 (F08) | `test_spec_solvers.py::test_calendar_conflict_strict_capacity` |

## Вне области

- Выбор весов и долей (навык `skeleton`, [skills-core.md](skills-core.md)).
- Ручные часы тем и решение конфликта методистом ([agent-workflow.md](agent-workflow.md)).
- Проверка сходимости часов правилами V-01…V-07 и V-10 ([validation-rules.md](validation-rules.md)).
- Производственный календарь с праздниками.
