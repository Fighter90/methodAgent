# Навык content

Префикс требований: `SPEC-CONTENT`. Код: `src/app/skills/content/run.py`. Подробности — [docs/skills.md](../docs/skills.md#content). Тесты: `tests/test_spec_content.py`.

## Назначение

Содержание одного модуля утверждённого каркаса: рабочая программа (аннотация, тексты тем), тест с ключами, задания с критериями, планы лекций и слайды, источники, вопросы собеседования для стажировки (FR-25…FR-29). Если модель недоступна, модуль собирается по шаблону из каркаса, и комплект остаётся полным.

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-CONTENT-01 | IF модель недоступна, THEN THE SYSTEM SHALL собрать модуль по шаблону (`source=template`) без вызова модели: аннотация из РО модуля, тексты тем из описаний, контрольный вопрос на каждую тему. | FR-25 | `test_spec_content.py::test_fallback_when_model_disabled` |
| SPEC-CONTENT-02 | WHEN тест собирается по шаблону, THE SYSTEM SHALL создать ровно `n_questions` вопросов с 4 разными вариантами, где верный ответ — РО темы, ключ чередуется `i % 4`, а дистракторы взяты из РО и тем других модулей. | FR-26 | `test_spec_content.py::test_fallback_questions` |
| SPEC-CONTENT-03 | WHEN задания и лекции собираются по шаблону, THE SYSTEM SHALL создать по заданию на тему с практикой с критериями 4 + 4 + 2 балла и лекции с 5 слайдами только для тем из `slide_topics`, длительностью `max(45, lk × 45)` мин. | FR-27, FR-28 | `test_spec_content.py::test_fallback_tasks_and_lectures` |
| SPEC-CONTENT-04 | WHILE программа — стажировка, THE SYSTEM SHALL создавать шаблонное задание стажировки для каждой темы, в том числе без часов практики. | FR-27 | `test_spec_content.py::test_fallback_internship_tasks_every_topic` |
| SPEC-CONTENT-05 | IF модель ответила ошибкой или ответ не прошёл схему, THEN THE SYSTEM SHALL собрать модуль по шаблону без исключения. | NFR-08 | `test_spec_content.py::test_fallback_on_model_error` |
| SPEC-CONTENT-06 | WHEN модель вернула содержание, THE SYSTEM SHALL отметить `source=llm`, подставить аннотацию и тексты тем по умолчанию для пустых, заменить ключ вне диапазона на 0, перевести коды РО в id (иначе РО по кругу) и добрать недостающие вопросы шаблоном с перенумерацией. | FR-26 | `test_spec_content.py::test_llm_content_mapped` |
| SPEC-CONTENT-07 | WHEN модель вернула задания, THE SYSTEM SHALL привязать задание к теме по номеру (иначе по кругу), поднять баллы критериев до не меньше 1 и выдать критерии по умолчанию, если их нет. | FR-27 | `test_spec_content.py::test_llm_tasks_criteria` |
| SPEC-CONTENT-08 | WHEN модель вернула лекции, THE SYSTEM SHALL создать лекции только для тем из `slide_topics` (до 8 слайдов по 6 тезисов, пример кода, минуты плана по умолчанию 10), для темы без слайдов модели — шаблонную лекцию, и оставить до 3 источников и до 6 вопросов собеседования длиннее 15 символов. | FR-28, FR-29 | `test_spec_content.py::test_llm_lectures_sources_interview` |
| SPEC-CONTENT-09 | IF модель не вернула заданий, THEN THE SYSTEM SHALL взять задания из шаблона. | FR-27 | `test_spec_content.py::test_llm_without_tasks_uses_template_tasks` |
| SPEC-CONTENT-10 | WHEN модель вызывается, THE SYSTEM SHALL передать темы с кодами РО и признаком практики, число вопросов, признак слайдов и версии только тех инструментов реестра, что встречаются в программе, а без слайдов ограничить ответ 4500 токенами. | FR-26, FR-30 | `test_spec_content.py::test_llm_request_payload` |
| SPEC-CONTENT-11 | WHEN ответ модели упоминает сервисы, недоступные в России, THE SYSTEM SHALL отбросить такие вопросы (их место займут шаблонные) и заменить упоминания в остальном тексте на «зарубежный сервис». | код | `test_spec_content.py::test_blocked_services_removed_from_llm_content`, `test_extras.py::test_blocked_services_scrubbed` |
| SPEC-CONTENT-12 | IF список заблокированных сервисов пуст, THEN THE SYSTEM SHALL вернуть ответ модели без изменений. | код | `test_spec_content.py::test_scrub_without_blocklist` |

## Вне области

Качество текстов модели, промпт `SKILL.md`, параллельная генерация модулей и пометка модулей-черновиков в `kit.drafts` (в `workflow.generate_kit`), фрагменты документов организации и НПА в запросе (передаются, но не проверяются).
