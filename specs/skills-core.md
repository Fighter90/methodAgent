# Каталог навыков и навыки до каркаса

Префикс требований: `SPEC-SKILLS`. Код: `src/app/skills/base.py`, `src/app/skills/intake/run.py`, `src/app/skills/classify/run.py`, `src/app/skills/clarify/run.py`, `src/app/skills/skeleton/run.py`, `src/app/skills/skeleton/library.py`. Подробности — [docs/skills.md](../docs/skills.md).

## Назначение

Навык — каталог `src/app/skills/<имя>/` с `SKILL.md` (параметры вызова модели и системный промпт), `schema_in.json` и `run.py`. `base.py` читает каталог и накладывает переопределения администратора. Навыки этого файла ведут программу от запроса до каркаса: `intake` (разбор запроса), `classify` (тип, шаблон, нормативная база, ПС), `clarify` (уточняющие вопросы и допущения), `skeleton` (цель, компетенции, РО, модули и темы с весами).

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-SKILLS-01 | THE SYSTEM SHALL находить все навыки по файлам `skills/*/SKILL.md` (заголовок YAML: `name`, `description`, `version`, параметры модели) и отдавать их список. | NFR-16 | `test_extras.py::test_skills_list_endpoint`, `test_auth.py::test_skill_override_and_reset` |
| SPEC-SKILLS-02 | WHEN администратор переопределяет `temperature`, `max_tokens`, `timeout_s`, `retries` или `instruction` навыка, THE SYSTEM SHALL сохранить переопределение в `data_dir/skills_overrides.json` и сразу применять его; WHEN выполнен сброс, THE SYSTEM SHALL вернуть исходные значения. | NFR-16 | `test_auth.py::test_skill_override_and_reset` |
| SPEC-SKILLS-03 | IF значение параметра навыка вне допустимого диапазона (например, `temperature` вне 0–1), THEN THE SYSTEM SHALL отклонить его с 400. | NFR-16 | `test_auth.py::test_skill_override_and_reset` |
| SPEC-SKILLS-04 | IF запрошен навык с неизвестным именем, THEN THE SYSTEM SHALL сообщить об ошибке (`KeyError`, в API — 404). | код | `test_spec_misc.py::test_unknown_skill` |
| SPEC-SKILLS-05 | WHEN разбирается запрос, THE SYSTEM SHALL без модели извлекать тип, объём, срок, форму, нагрузку, часы ИА и материалы, и числа из текста SHALL иметь приоритет над ответом модели. | FR-01, FR-03 | `test_core.py::test_open_cases_auto` |
| SPEC-SKILLS-06 | IF модель недоступна, THEN THE SYSTEM SHALL определять аудиторию, входной уровень и темы эвристиками по тексту запроса. | FR-03, FR-19 | `test_spec_misc.py::test_intake_heuristics_without_llm` |
| SPEC-SKILLS-07 | WHEN классифицируется программа, THE SYSTEM SHALL брать тип из параметров, иначе по словам «школьник», «детей» и т. п. определять ДООП, назначать шаблон и выдаваемый документ, подбирать нормативную базу и (только для ДПП) ПС из реестра. | FR-06, FR-07 | `test_spec_misc.py::test_classify_type_template_norms_ps` |
| SPEC-SKILLS-08 | THE SYSTEM SHALL задавать не больше 5 уточняющих вопросов и только по пустым обязательным полям, каждый — с вариантами ответа. | FR-11, FR-12 | `test_spec_misc.py::test_clarify_questions_only_for_missing` |
| SPEC-SKILLS-09 | WHEN ответ «на ваше усмотрение» или режим `auto`, THE SYSTEM SHALL брать значение из `defaults` профиля организации (иначе из встроенных умолчаний) и записывать его в допущения. | FR-13 | `test_access.py::test_admin_profile_registry_and_expert_suggestions`, `test_skeleton.py::test_topic_hours_manual_and_assumptions` |
| SPEC-SKILLS-10 | WHEN строится каркас, THE SYSTEM SHALL получать от модели только структуру и веса (до 8 компетенций, 12 модулей, 8 тем в модуле, доли ЛК и СРС в пределах 0–0.6), а часы оставлять солверу. | FR-14, FR-16 | `test_spec_misc.py::test_skeleton_llm_structure_limits` |
| SPEC-SKILLS-11 | WHEN сопоставляется ТФ компетенции, THE SYSTEM SHALL принимать код модели только если он есть в ПС, иначе выбирать ТФ по совпадению основ слов. | FR-14 | `test_skeleton.py::test_match_tf_by_meaning` |
| SPEC-SKILLS-12 | WHEN каркас от модели содержит модули итоговой аттестации, THE SYSTEM SHALL убирать их (если остаётся не меньше двух модулей) и добавлять обязательные темы направления в ближайший по смыслу модуль. | FR-14 | `test_extras.py::test_skeleton_guards` |
| SPEC-SKILLS-13 | IF модель недоступна или вернула меньше двух модулей, THEN THE SYSTEM SHALL собрать каркас из библиотеки типовых доменов или общего шаблона. | FR-19, NFR-08 | `test_spec_misc.py::test_skeleton_fallback_library` |
| SPEC-SKILLS-14 | THE SYSTEM SHALL связывать каждый РО хотя бы с одной темой и каждую тему хотя бы с одним РО. | FR-34 | `test_spec_misc.py::test_link_outcomes_both_ways` |

## Вне области

- Навыки `content` и `review_assist` — [skill-content.md](skill-content.md), [skill-review-assist.md](skill-review-assist.md).
- Вызов модели, бюджеты, повторы — [llm-client.md](llm-client.md).
- Навыки, реализованные в других пакетах (`hours_solver`, `validate`, `repair`, `export`, `workflow`) — их спецификации.
