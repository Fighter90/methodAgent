# Автоисправление (repair)

Префикс требований: `SPEC-REPAIR`. Код: `src/app/validation/repair.py`. Подробности — [docs/validation.md](../docs/validation.md#автоисправление-repairpy). Тесты: `tests/test_spec_repair.py`.

## Назначение

`repair(doc, rules)` детерминированно, без вызова модели, исправляет элементы программы и комплекта, не прошедшие правила V-08, V-09, V-11, V-13, V-14, V-16…V-19, и возвращает журнал исправлений для методиста. Вызывается из `generate_kit` не больше двух проходов (FR-34); то, что не исправлено, остаётся в отчёте. `cover_outcomes` добавляет вопросы теста для РО, которые проверяются одним средством.

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-REPAIR-01 | IF среди результатов правил нет статуса `fail`, THEN THE SYSTEM SHALL оставить документ без изменений и вернуть пустой журнал. | FR-34 | `test_spec_repair.py::test_no_failed_rules_no_changes` |
| SPEC-REPAIR-02 | WHEN V-19 не пройдено, THE SYSTEM SHALL убрать повторяющиеся (после обрезки пробелов) варианты ответа, добрать список до 4 вариантов «Другой вариант N», заменить ключ вне диапазона на 0 и записать каждое исправление в журнал. | FR-34, FR-26 | `test_spec_repair.py::test_v19_duplicates_removed_and_key_fixed` |
| SPEC-REPAIR-03 | WHEN V-19 убирает повторы вариантов, THE SYSTEM SHALL сохранить ключ на том же тексте верного ответа. | FR-26 | `test_spec_repair.py::test_v19_key_keeps_correct_answer` (xfail) |
| SPEC-REPAIR-04 | WHEN V-18 не пройдено, THE SYSTEM SHALL заменить критерии задания без критериев или с баллами ≤ 0 рубрикой из трёх критериев 4 + 4 + 2 балла, не трогая корректные задания. | FR-27 | `test_spec_repair.py::test_v18_rubric_added` |
| SPEC-REPAIR-05 | WHEN V-14 не пройдено, THE SYSTEM SHALL удалить ссылки на несуществующие РО и привязать задание без валидных РО к РО его темы, а вопрос — к одному из РО его модуля. | FR-34 | `test_spec_repair.py::test_v14_bindings_to_existing_outcomes` |
| SPEC-REPAIR-06 | THE SYSTEM SHALL выбирать РО для вопроса без валидной привязки детерминированно, независимо от процесса и `PYTHONHASHSEED`. | NFR-09 | `test_spec_repair.py::test_v14_choice_is_deterministic_across_processes` (xfail) |
| SPEC-REPAIR-07 | WHEN V-13 или V-14 не пройдено, THE SYSTEM SHALL добавить каждый РО, проверяемый менее чем двумя средствами, в критерии итоговой аттестации и добрать покрытие вопросами теста модуля так, чтобы каждый РО проверялся не меньше чем двумя средствами. | FR-34 | `test_spec_repair.py::test_v13_final_and_question_cover_outcome` |
| SPEC-REPAIR-08 | WHEN `cover_outcomes` добавляет вопрос, THE SYSTEM SHALL сформировать 4 варианта, где вариант по ключу — формулировка РО, привязать вопрос к РО и тесту `test-<модуль>`, присвоить уникальный id и при необходимости создать оценочное средство «Тест М<n>». | FR-26 | `test_spec_repair.py::test_cover_outcomes_question_shape` |
| SPEC-REPAIR-09 | IF в комплекте есть итоговый тест `test-final`, THEN THE SYSTEM SHALL добавлять вопросы в него (id `qf.N`); IF РО уже проверяется тестом, THEN THE SYSTEM SHALL добавить РО в задание семинара его модуля. | код | `test_spec_repair.py::test_cover_outcomes_final_test_and_seminar` |
| SPEC-REPAIR-10 | IF объём теста задан в запросе, THEN THE SYSTEM SHALL заменять новым вопросом «лишний» вопрос по РО, который проверяется несколькими вопросами, сохраняя число вопросов теста. | FR-26 | `test_spec_repair.py::test_cover_outcomes_replaces_spare_when_volume_fixed` |
| SPEC-REPAIR-11 | WHEN V-09 не пройдено, THE SYSTEM SHALL привести тему лекции к теме УТП и собрать слайды модулям из запроса (или первому модулю, если слайдов нет нигде) по описанию темы и плану лекции с пометкой «нужна вычитка эксперта». | FR-28 | `test_spec_repair.py::test_v09_lecture_titles_and_slides` |
| SPEC-REPAIR-12 | IF у модуля из запроса слайды уже есть, THEN THE SYSTEM SHALL не пересобирать их. | FR-28 | `test_spec_repair.py::test_v09_respects_requested_modules_with_slides` |
| SPEC-REPAIR-13 | WHEN V-17 не пройдено, THE SYSTEM SHALL удалить из аннотаций, текстов рабочих программ и описаний тем предложения, совпадающие с референсом по 8-граммам, и записать их число в журнал. | FR-34 | `test_spec_repair.py::test_v17_reference_overlap_removed` |
| SPEC-REPAIR-14 | IF текста референса нет, THEN THE SYSTEM SHALL ничего не удалять по V-17. | код | `test_spec_repair.py::test_v17_without_reference_noop` |
| SPEC-REPAIR-15 | WHEN V-08 или V-11 не пройдено, THE SYSTEM SHALL пересобрать разделы шаблона из графа программы, оставив реквизиты и ФИО полями. | FR-25, NFR-11 | `test_spec_repair.py::test_v08_v11_sections_rebuilt` |
| SPEC-REPAIR-16 | WHEN V-16 не пройдено, THE SYSTEM SHALL пометить каждый неподтверждённый источник «[не подтверждено]» ровно один раз и не менять подтверждённые. | FR-29 | `test_spec_repair.py::test_v16_unconfirmed_sources_marked_once` |

## Известные расхождения

Нет. Оба найденных расхождения исправлены в v20:

- SPEC-REPAIR-03: при V-19 ключ пересчитывается по тексту верного ответа после удаления повторов.
- SPEC-REPAIR-06: при V-14 индекс РО считается через `zlib.crc32(q.id)`, результат одинаков в любом процессе.

## Вне области

Порядок и число проходов repair (цикл в `generate_kit`), сами правила V-01…V-27 (см. [validation-rules.md](validation-rules.md)), качество текста собранных слайдов и разделов.
