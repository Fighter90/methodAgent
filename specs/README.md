# Спецификации (SDD)

МетодАгент разрабатывается по спецификациям (spec-driven development, SDD): у каждого модуля есть спецификация в `specs/` с пронумерованными требованиями, тесты ссылаются на ID требований в докстрингах, а код пишется под тесты. Порядок всегда один: **спецификация → тесты → код**. Спецификация — источник истины о наблюдаемом поведении модуля; документация в `docs/` объясняет устройство и не заменяет её.

## Формат требований: EARS (ТЗ, п. 4.11)

ТЗ (п. 4.11) требует записывать требования в нотации EARS (Easy Approach to Requirements Syntax). Ключевые слова пишутся латиницей, остальное — по-русски; одно требование — одно проверяемое поведение системы.

| Шаблон | Когда применять | Пример |
|---|---|---|
| `THE SYSTEM SHALL …` | всегда действующее требование | THE SYSTEM SHALL хранить пароли только хешем bcrypt. |
| `WHEN <событие>, THE SYSTEM SHALL …` | реакция на событие | WHEN методист меняет часы тем каркаса, THE SYSTEM SHALL сохранить ручное распределение. |
| `WHILE <состояние>, THE SYSTEM SHALL …` | поведение в состоянии | WHILE активная роль — `expert`, THE SYSTEM SHALL показывать только назначенные модули. |
| `IF <нежелательная ситуация>, THEN THE SYSTEM SHALL …` | ошибки и отказы | IF каркас не утверждён, THEN THE SYSTEM SHALL отказать в генерации комплекта. |
| `WHERE <функция включена>, THE SYSTEM SHALL …` | необязательные возможности | WHERE включён судья, THE SYSTEM SHALL уточнять смысловые правила моделью. |

Шаблоны можно сочетать в одном предложении («WHEN …, THE SYSTEM SHALL …; IF …, THEN THE SYSTEM SHALL …»), если это одно поведение.

## Структура файла спецификации

1. Заголовок, префикс требований и перечень файлов кода.
2. **Назначение** — что делает модуль и где его границы.
3. **Требования** — таблица `ID | Требование | Источник | Тест`:
   - `ID` — `SPEC-<MODULE>-NN`: `MODULE` — короткий префикс модуля латиницей (`AUTH`, `FLOW`, `SOLVER`, `RULES`, `KB`, `EXPORT`, `API`, `SKILLS`, `UI` и префиксы других файлов), `NN` — двузначный номер. ID не переиспользуются: удалённое требование оставляет пропуск в нумерации.
   - `Требование` — наблюдаемое поведение в нотации EARS (что видно снаружи: ответ API, состояние документа, файл), а не способ реализации.
   - `Источник` — номер требования ТЗ (FR-NN, NFR-NN, «Доп.» — по `analysis/tz-compliance.md`) или «код», если требование выведено из существующего кода.
   - `Тест` — тесты вида `test_файл.py::test_функция`, которые проверяют требование, или «—», если теста пока нет.
4. **Вне области** — что модуль сознательно не делает и где это описано.

## Как начинается изменение

1. **Спецификация.** Добавьте или измените требование в нужном `specs/*.md` (новый ID — следующий свободный номер). Для нового модуля создайте файл по структуре выше и добавьте его в перечень ниже.
2. **Тест.** Добавьте или поправьте тест; первой строкой его докстринга перечислите ID требований через запятую:

   ```python
   def test_module_accept_requires_all_items(client, kit) -> None:
       """SPEC-FLOW-17, SPEC-API-13"""
   ```

   Если у теста уже есть описание, ID идут первой строкой, описание — после пустой строки. Впишите тест в колонку «Тест» требования. Убедитесь, что тест падает на старом коде (или явно фиксирует существующее поведение).
3. **Код.** Измените код в `src/app` или `frontend/src`, пока тесты не станут зелёными.
4. **Документация.** Обновите `docs/*.md` и `docs/changelog.md`, если меняется описанное там поведение.

Исправление ошибки начинается так же: сначала требование (или уточнение существующего), затем тест, воспроизводящий ошибку, затем исправление.

## Готово, когда

- `PYTHONPATH=src pytest -q` — все тесты зелёные (тесты не ходят в сеть: `LLM_PROVIDERS=fixtures`).
- Покрытие кода не ниже 60 %: порог задан в `.coveragerc` (`fail_under = 60`) и проверяется прогоном `PYTHONPATH=src pytest -q --cov --cov-config=.coveragerc` (pytest-cov из `requirements-dev.txt`).
- `ruff check` без замечаний.
- `python scripts/spec_trace.py` завершается с кодом 0: нет ссылок на неизвестные ID (то же проверяет `tests/test_spec_trace.py`).
- Спецификация и документация в `docs/` отражают новое поведение; колонка «Тест» заполнена для покрытых требований.

## Трассировка

`scripts/spec_trace.py` читает таблицы требований из `specs/*.md` (строки, первая ячейка которых — ID) и докстринги всех тестов в `tests/` (модуль, классы, функции) и печатает по каждому файлу спецификации число требований, сколько из них упомянуто в тестах и непокрытые ID. Скрипт ничего не записывает.

```bash
python scripts/spec_trace.py             # сводка; код 1, если тест ссылается на неизвестный ID
python scripts/spec_trace.py --markdown  # таблица «требование → тест» (вставляется в этот файл)
```

Также выводятся предупреждения: ID объявлен дважды; тест назван в колонке «Тест», но в его докстринге нет ID. Неизвестный ID в тесте — ошибка: требование нужно сначала добавить в спецификацию. Непокрытое требование — не ошибка, а долг: «—» в колонке «Тест» показывает, где тестов не хватает (например, интерфейс проверяется вручную).

## Перечень спецификаций

| Файл | Префикс | Что описывает |
|---|---|---|
| [auth-and-roles.md](auth-and-roles.md) | `SPEC-AUTH` | Вход, токены и `X-MA-Token`, регистрация, демо-учётки, разделение пяти ролей, администрирование пользователей, шифрование секретов |
| [agent-workflow.md](agent-workflow.md) | `SPEC-FLOW` | Конвейер агента: состояния программы, режимы interactive/auto, каркас, решения по «!», точечная правка, вычитка, согласование, версии, адаптация, актуализация, разделы шаблона |
| [solvers.md](solvers.md) | `SPEC-SOLVER` | Детерминированные солверы часов (метод наибольших остатков) и календарного графика с вариантами разрешения конфликта |
| [validation-rules.md](validation-rules.md) | `SPEC-RULES` | 27 правил V-01…V-27, 10 блокирующих проверок, отчёт агента, матрица покрытия, 8-граммы |
| [validation-repair.md](validation-repair.md) | см. файл | Детерминированное автоисправление нарушений правил (repair) |
| [validation-sandbox.md](validation-sandbox.md) | см. файл | Песочница для примеров кода: изоляция, лимиты, режимы skip/syntax/run |
| [validation-judge.md](validation-judge.md) | см. файл | Модель-судья для смысловых правил V-21, V-22, V-26, V-27 и слияние её замечаний с отчётом |
| [knowledge-base.md](knowledge-base.md) | `SPEC-KB` | Реестры НПА/ПС/литературы, выжимки актов, документы организации, разбор файлов и таблиц часов, профиль и реестры через API |
| [export.md](export.md) | `SPEC-EXPORT` | Выгрузка в DOCX, лекции DOCX, проект приказа, PPTX, GIFT, Moodle XML, JSON 4.8 |
| [api.md](api.md) | `SPEC-API` | REST API `/api/v1`: формат ошибок, задания, программы, вычитка, уведомления, служебные методы |
| [programs-service.md](programs-service.md) | см. файл | Хранение программ, версий, событий, уведомлений и заданий (`programs/service.py`) |
| [skills-core.md](skills-core.md) | `SPEC-SKILLS` | Каталог навыков и переопределения администратора; навыки intake, classify, clarify, skeleton |
| [skill-content.md](skill-content.md) | см. файл | Навык content: содержание модуля, резерв без модели, фильтр недоступных сервисов |
| [skill-review-assist.md](skill-review-assist.md) | см. файл | Навык review_assist: предложение правки по комментарию эксперта |
| [llm-client.md](llm-client.md) | см. файл | Клиент шлюза LLM: повторы, резервная модель, бюджеты времени и денег, суточный лимит, эмбеддинги |
| [frontend.md](frontend.md) | `SPEC-UI` | Интерфейс: маршруты, экраны по ролям, `X-MA-Token`, повторы и работа при недоступном сервере |

## Сводная трассировка «требование → тест»

Сгенерировано `python scripts/spec_trace.py --markdown`; после изменения спецификаций или тестов перегенерируйте блок.

<!-- trace:begin -->
| Спецификация | Требований | Покрыто | Не покрыты |
|---|---|---|---|
| [agent-workflow.md](agent-workflow.md) | 46 | 46 | — |
| [api.md](api.md) | 36 | 36 | — |
| [auth-and-roles.md](auth-and-roles.md) | 30 | 30 | — |
| [export.md](export.md) | 14 | 14 | — |
| [frontend.md](frontend.md) | 30 | 0 | SPEC-UI-01, SPEC-UI-02, SPEC-UI-03, SPEC-UI-04, SPEC-UI-05, SPEC-UI-06, SPEC-UI-07, SPEC-UI-08, SPEC-UI-09, SPEC-UI-10, SPEC-UI-11, SPEC-UI-12, SPEC-UI-13, SPEC-UI-14, SPEC-UI-15, SPEC-UI-16, SPEC-UI-17, SPEC-UI-18, SPEC-UI-19, SPEC-UI-20, SPEC-UI-21, SPEC-UI-22, SPEC-UI-23, SPEC-UI-24, SPEC-UI-25, SPEC-UI-26, SPEC-UI-27, SPEC-UI-28, SPEC-UI-29, SPEC-UI-30 |
| [knowledge-base.md](knowledge-base.md) | 21 | 21 | — |
| [llm-client.md](llm-client.md) | 26 | 26 | — |
| [programs-service.md](programs-service.md) | 16 | 16 | — |
| [skill-content.md](skill-content.md) | 15 | 15 | — |
| [skill-review-assist.md](skill-review-assist.md) | 5 | 5 | — |
| [skills-core.md](skills-core.md) | 19 | 19 | — |
| [solvers.md](solvers.md) | 16 | 16 | — |
| [validation-judge.md](validation-judge.md) | 8 | 8 | — |
| [validation-repair.md](validation-repair.md) | 18 | 18 | — |
| [validation-rules.md](validation-rules.md) | 23 | 23 | — |
| [validation-sandbox.md](validation-sandbox.md) | 13 | 13 | — |

| Требование | Тесты |
|---|---|
| SPEC-FLOW-01 | `test_skeleton.py::test_topic_hours_manual_and_assumptions` |
| SPEC-FLOW-02 | `test_access.py::test_auto_async_returns_202_and_job_result`, `test_core.py::test_open_cases_auto` |
| SPEC-FLOW-03 | `test_core.py::test_open_cases_auto` |
| SPEC-FLOW-04 | `test_spec_misc.py::test_auto_run_exception_marks_failed` |
| SPEC-FLOW-05 | `test_skeleton.py::test_topic_hours_manual_and_assumptions` |
| SPEC-FLOW-06 | `test_skeleton.py::test_topic_hours_manual_and_assumptions` |
| SPEC-FLOW-07 | `test_spec_misc.py::test_patch_skeleton_locked` |
| SPEC-FLOW-08 | `test_skeleton.py::test_decisions_per_node` |
| SPEC-FLOW-09 | `test_spec_misc.py::test_approve_skeleton_errors_and_pending` |
| SPEC-FLOW-10 | `test_spec_misc.py::test_generate_requires_approved_skeleton` |
| SPEC-FLOW-11 | `test_spec_misc.py::test_return_with_comment_passes_current_skeleton` |
| SPEC-FLOW-12 | `test_skeleton.py::test_fit_plan_sums_to_duration`, `test_skeleton.py::test_calendar_kinds_and_lecture_plans` |
| SPEC-FLOW-13 | `test_access.py::test_edit_hours_keeps_module_total_and_text_edit_finds_target` |
| SPEC-FLOW-14 | `test_access.py::test_edit_hours_keeps_module_total_and_text_edit_finds_target` |
| SPEC-FLOW-15 | `test_spec_misc.py::test_edit_rollback_and_new_version` |
| SPEC-FLOW-16 | `test_access.py::test_expert_sees_only_own_modules_and_accepts_items` |
| SPEC-FLOW-17 | `test_access.py::test_expert_sees_only_own_modules_and_accepts_items`, `test_access.py::test_module_accept_requires_all_items`, `test_access.py::test_unassigned_expert_cannot_accept_and_api_404` |
| SPEC-FLOW-18 | `test_access.py::test_expert_sees_only_own_modules_and_accepts_items` |
| SPEC-FLOW-19 | `test_spec_misc.py::test_submit_and_head_decision` |
| SPEC-FLOW-20 | `test_access.py::test_head_sees_quality_and_owners` |
| SPEC-FLOW-21 | `test_access.py::test_head_sees_quality_and_owners` |
| SPEC-FLOW-22 | `test_access.py::test_restore_does_not_bring_back_approval` |
| SPEC-FLOW-23 | `test_extras.py::test_versions_diff_and_sections` |
| SPEC-FLOW-24 | `test_extras.py::test_change_template_before_approval` |
| SPEC-FLOW-25 | `test_e2e_regressions.py::test_api_client_cannot_adapt_foreign_program`, `test_extras.py::test_adapt_keeps_competencies_and_resolves_hours` |
| SPEC-FLOW-26 | `test_extras.py::test_actualize_text_and_program` |
| SPEC-FLOW-27 | `test_extras.py::test_sandbox_and_tasks` |
| SPEC-FLOW-28 | `test_extras.py::test_sandbox_and_tasks` |
| SPEC-FLOW-29 | `test_access.py::test_admin_profile_registry_and_expert_suggestions` |
| SPEC-FLOW-30 | `test_extras.py::test_versions_diff_and_sections` |
| SPEC-FLOW-31 | `test_extras.py::test_interview_questions_vary` |
| SPEC-FLOW-32 | `test_spec_misc.py::test_sources_confirmed_or_marked` |
| SPEC-FLOW-33 | `test_spec_misc.py::test_norm_and_org_fragments` |
| SPEC-FLOW-34 | `test_spec_misc.py::test_auto_calendar_conflict_choice` |
| SPEC-FLOW-35 | `test_tz_compliance.py::test_auto_calendar_choice_refreshes_skeleton_report` |
| SPEC-FLOW-36 | `test_tz_compliance.py::test_expert_comment_proposal_needs_expert_confirmation` |
| SPEC-FLOW-37 | `test_tz_compliance.py::test_changed_accepted_module_returns_to_review_and_notifies_expert` |
| SPEC-FLOW-38 | `test_spec_robustness.py::test_parallel_generation_is_deterministic` |
| SPEC-FLOW-39 | `test_spec_robustness.py::test_module_failure_is_isolated_and_recorded` |
| SPEC-FLOW-40 | `test_spec_robustness.py::test_pptx_slides_without_llm`, `test_spec_robustness.py::test_pptx_slides_when_content_skill_unavailable`, `test_spec_robustness.py::test_slides_guaranteed_when_content_returns_none` |
| SPEC-FLOW-41 | `test_spec_misc.py::test_question_edit_keeps_lo_links` |
| SPEC-FLOW-42 | `test_spec_misc.py::test_source_url_reachability_is_not_confirmation` |
| SPEC-FLOW-43 | `test_e2e_regressions.py::test_restore_keeps_program_consistent` |
| SPEC-FLOW-44 | `test_spec_misc.py::test_v21_swap_reorders_by_dependency_graph`, `test_spec_misc.py::test_v21_cycle_blocks_silent_approval` |
| SPEC-FLOW-45 | `test_spec_misc.py::test_slide_hint_finds_module_by_any_topic` |
| SPEC-FLOW-46 | `test_e2e_regressions.py::test_return_with_comment_reports_changes`, `test_spec_misc.py::test_return_rebuild_lists_changes` |
| SPEC-API-01 | `test_access.py::test_unassigned_expert_cannot_accept_and_api_404` |
| SPEC-API-02 | `test_access.py::test_module_accept_requires_all_items`, `test_auth.py::test_register_gets_minimal_role_and_cabinet` |
| SPEC-API-03 | `test_auth.py::test_register_gets_minimal_role_and_cabinet` |
| SPEC-API-04 | `test_spec_misc.py::test_unhandled_error_hides_details` |
| SPEC-API-05 | `test_access.py::test_unassigned_expert_cannot_accept_and_api_404` |
| SPEC-API-06 | `test_access.py::test_auto_async_returns_202_and_job_result` |
| SPEC-API-07 | `test_core.py::test_open_cases_auto` |
| SPEC-API-08 | `test_spec_misc.py::test_request_limits` |
| SPEC-API-09 | `test_extras.py::test_head_filter` |
| SPEC-API-10 | `test_extras.py::test_versions_diff_and_sections` |
| SPEC-API-11 | `test_access.py::test_restore_does_not_bring_back_approval`, `test_extras.py::test_versions_diff_and_sections` |
| SPEC-API-12 | `test_access.py::test_expert_sees_only_own_modules_and_accepts_items`, `test_access.py::test_restore_does_not_bring_back_approval`, `test_e2e_regressions.py::test_head_decisions_logged_in_words` |
| SPEC-API-13 | `test_access.py::test_expert_sees_only_own_modules_and_accepts_items`, `test_access.py::test_module_accept_requires_all_items` |
| SPEC-API-14 | `test_access.py::test_expert_sees_only_own_modules_and_accepts_items` |
| SPEC-API-15 | `test_extras.py::test_sandbox_and_tasks` |
| SPEC-API-16 | `test_extras.py::test_skills_list_endpoint` |
| SPEC-API-17 | `test_auth.py::test_skill_override_and_reset` |
| SPEC-API-18 | `test_extras.py::test_actualize_text_and_program` |
| SPEC-API-19 | `test_spec_misc.py::test_parallel_jobs_limit` |
| SPEC-API-20 | `test_spec_misc.py::test_resume_jobs_on_start` |
| SPEC-API-21 | `test_spec_misc.py::test_cors_and_docs` |
| SPEC-API-22 | `test_spec_misc.py::test_llm_status` |
| SPEC-API-23 | `test_extras.py::test_kb_upload_and_search` |
| SPEC-API-24 | `test_spec_effect.py`, `test_spec_effect.py::test_autorun_reports_effect` |
| SPEC-API-25 | `test_spec_robustness.py::test_interactive_returns_questions_and_resumes`, `test_spec_robustness.py::test_answers_then_auto_completes_kit`, `test_spec_robustness.py::test_answers_endpoint_checks_owner` |
| SPEC-API-26 | `test_spec_robustness.py::test_auto_lists_assumptions_for_missing_fields` |
| SPEC-API-27 | `test_reproducibility.py::test_images_pinned_and_lock_files_cover_requirements` |
| SPEC-API-28 | `test_reproducibility.py::test_openapi_schema_matches_code` |
| SPEC-API-29 | `test_spec_tokens.py::test_env_settings_table_26` |
| SPEC-API-30 | `test_autorun_checks.py`, `test_autorun_checks.py::test_export_problems_rejects_broken_files`, `test_autorun_checks.py::test_real_exports_pass_structural_checks`, `test_autorun_checks.py::test_run_ok_when_all_checks_pass`, `test_autorun_checks.py::test_run_fails_on_http_error`, `test_autorun_checks.py::test_run_polls_202_job`, `test_autorun_checks.py::test_run_fails_on_status_check_and_broken_export`, `test_autorun_checks.py::test_case1_slides_check_requires_first_two_topics`, `test_autorun_checks.py::test_case5_interview_check_requires_interview_questions` |
| SPEC-API-31 | `test_access.py::test_approve_atomic_capacity_first_and_idempotent_job` |
| SPEC-API-32 | `test_access.py::test_expert_view_filters_foreign_content` |
| SPEC-API-33 | `test_spec_constraints.py::test_constraints_check_passes` |
| SPEC-API-34 | `test_access.py::test_expert_accepts_every_item_type_without_500` |
| SPEC-API-35 | `test_access.py::test_admin_profile_registry_and_expert_suggestions` |
| SPEC-API-36 | `test_access.py::test_attachment_validated_before_decode` |
| SPEC-AUTH-01 | `test_auth.py::test_login_by_login_id_and_all_demo_users` |
| SPEC-AUTH-02 | `test_auth.py::test_login_by_login_id_and_all_demo_users`, `test_auth.py::test_register_gets_minimal_role_and_cabinet` |
| SPEC-AUTH-03 | `test_auth.py::test_login_by_login_id_and_all_demo_users` |
| SPEC-AUTH-04 | `test_access.py::test_no_token_cannot_read_others`, `test_extras.py::test_anonymous_limited_to_auto_and_reads` |
| SPEC-AUTH-05 | `test_spec_misc.py::test_anon_rate_limit` |
| SPEC-AUTH-06 | `test_auth.py::test_admin_manages_users_but_not_programs`, `test_core.py::test_roles` |
| SPEC-AUTH-07 | `test_auth.py::test_admin_manages_users_but_not_programs`, `test_core.py::test_roles` |
| SPEC-AUTH-08 | `test_access.py::test_expert_sees_only_own_modules_and_accepts_items`, `test_access.py::test_expert_view_filters_foreign_content`, `test_e2e_regressions.py::test_unassigned_expert_cannot_read_sections_or_actualize` |
| SPEC-AUTH-09 | `test_access.py::test_edit_hours_keeps_module_total_and_text_edit_finds_target`, `test_access.py::test_unassigned_expert_cannot_accept_and_api_404` |
| SPEC-AUTH-10 | `test_auth.py::test_register_gets_minimal_role_and_cabinet` |
| SPEC-AUTH-11 | `test_auth.py::test_registration_and_demo_switches` |
| SPEC-AUTH-12 | `test_auth.py::test_login_by_login_id_and_all_demo_users`, `test_auth.py::test_registration_and_demo_switches` |
| SPEC-AUTH-13 | `test_auth.py::test_register_gets_minimal_role_and_cabinet` |
| SPEC-AUTH-14 | `test_spec_misc.py::test_demo_account_cannot_change_profile` |
| SPEC-AUTH-15 | `test_auth.py::test_admin_manages_users_but_not_programs` |
| SPEC-AUTH-16 | `test_auth.py::test_admin_manages_users_but_not_programs` |
| SPEC-AUTH-17 | `test_spec_misc.py::test_passwords_bcrypt_only` |
| SPEC-AUTH-18 | `test_auth.py::test_settings_secret_masked_encrypted_and_applied` |
| SPEC-AUTH-19 | `test_spec_misc.py::test_secret_unreadable` |
| SPEC-AUTH-20 | `test_auth.py::test_admin_manages_users_but_not_programs`, `test_auth.py::test_settings_secret_masked_encrypted_and_applied` |
| SPEC-AUTH-21 | `test_auth.py::test_admin_manages_users_but_not_programs` |
| SPEC-AUTH-22 | `test_spec_misc.py::test_weak_secret_key_replaced` |
| SPEC-AUTH-23 | `test_auth.py::test_login_by_login_id_and_all_demo_users` |
| SPEC-AUTH-24 | `test_tz_compliance.py::test_login_failures_rate_limited` |
| SPEC-AUTH-25 | `test_spec_tokens.py::test_access_30_min_and_refresh_30_days` |
| SPEC-AUTH-26 | `test_spec_tokens.py::test_refresh_endpoint_and_token_types` |
| SPEC-AUTH-27 | `test_spec_tokens.py::test_admin_issues_lists_and_revokes_api_tokens` |
| SPEC-AUTH-28 | `test_spec_tokens.py::test_admin_issues_lists_and_revokes_api_tokens`, `test_spec_tokens.py::test_expired_api_token_rejected` |
| SPEC-AUTH-29 | `test_spec_tokens.py::test_program_creation_limit_per_user` |
| SPEC-AUTH-30 | `test_access.py::test_expert_node_must_belong_to_own_module` |
| SPEC-EXPORT-01 | `test_spec_export.py::test_formats_and_unknown` |
| SPEC-EXPORT-02 | `test_core.py::test_open_cases_auto` |
| SPEC-EXPORT-03 | `test_spec_export.py::test_human_fields_left_blank` |
| SPEC-EXPORT-04 | `test_access.py::test_json_export_follows_schema_48` |
| SPEC-EXPORT-05 | `test_spec_export.py::test_gift_and_moodle_xml` |
| SPEC-EXPORT-06 | `test_spec_export.py::test_pptx_16x9_and_fallback` |
| SPEC-EXPORT-07 | `test_spec_export.py::test_lectures_docx` |
| SPEC-EXPORT-08 | `test_spec_export.py::test_order_draft` |
| SPEC-EXPORT-09 | `test_spec_export.py::test_filename_and_disposition` |
| SPEC-EXPORT-10 | `test_access.py::test_no_token_cannot_read_others`, `test_access.py::test_expert_sees_only_own_modules_and_accepts_items` |
| SPEC-EXPORT-11 | `test_spec_export.py::test_auto_run_lists_all_exports` |
| SPEC-EXPORT-12 | `test_tz_compliance.py::test_dpp_curriculum_and_utp_headers_follow_template` |
| SPEC-EXPORT-13 | `test_tz_compliance.py::test_doop_staff_table_with_blank_names` |
| SPEC-EXPORT-14 | `test_spec_export.py::test_moodle_xml_cdata_roundtrip` |
| SPEC-UI-01 | — |
| SPEC-UI-02 | — |
| SPEC-UI-03 | — |
| SPEC-UI-04 | — |
| SPEC-UI-05 | — |
| SPEC-UI-06 | — |
| SPEC-UI-07 | — |
| SPEC-UI-08 | — |
| SPEC-UI-09 | — |
| SPEC-UI-10 | — |
| SPEC-UI-11 | — |
| SPEC-UI-12 | — |
| SPEC-UI-13 | — |
| SPEC-UI-14 | — |
| SPEC-UI-15 | — |
| SPEC-UI-16 | — |
| SPEC-UI-17 | — |
| SPEC-UI-18 | — |
| SPEC-UI-19 | — |
| SPEC-UI-20 | — |
| SPEC-UI-21 | — |
| SPEC-UI-22 | — |
| SPEC-UI-23 | — |
| SPEC-UI-24 | — |
| SPEC-UI-25 | — |
| SPEC-UI-26 | — |
| SPEC-UI-27 | — |
| SPEC-UI-28 | — |
| SPEC-UI-29 | — |
| SPEC-UI-30 | — |
| SPEC-KB-01 | `test_norms.py::test_repealed_acts_are_not_used` |
| SPEC-KB-02 | `test_norms.py::test_repealed_acts_are_not_used` |
| SPEC-KB-03 | `test_norms.py::test_core_and_keyword_acts` |
| SPEC-KB-04 | `test_norms.py::test_core_and_keyword_acts` |
| SPEC-KB-05 | `test_norms.py::test_profstandards_for_cases`, `test_spec_ps_audience.py::test_audience_keywords_keep_open_cases` |
| SPEC-KB-06 | `test_norms.py::test_norm_base_for_school_college_university` |
| SPEC-KB-07 | `test_norms.py::test_norm_digests_link_to_registry`, `test_norms.py::test_norm_base_for_school_college_university` |
| SPEC-KB-08 | `test_extras.py::test_sources_school_and_generic_docs` |
| SPEC-KB-09 | `test_extras.py::test_kb_upload_and_search` |
| SPEC-KB-10 | `test_extras.py::test_kb_upload_and_search` |
| SPEC-KB-11 | `test_extras.py::test_cyrillic_txt_cut_at_2000_bytes_is_text` |
| SPEC-KB-12 | `test_skeleton.py::test_pdf_reference_hours_checked` |
| SPEC-KB-13 | `test_extras.py::test_kb_docx_zip_bomb_rejected_and_normal_ok` |
| SPEC-KB-14 | `test_access.py::test_admin_profile_registry_and_expert_suggestions` |
| SPEC-KB-15 | `test_access.py::test_admin_profile_registry_and_expert_suggestions` |
| SPEC-KB-16 | `test_spec_ps_audience.py::test_ps_for_audience`, `test_spec_ps_audience.py::test_audience_keywords_keep_open_cases` |
| SPEC-KB-17 | `test_spec_kb_vectors.py`, `test_spec_kb_vectors.py::test_vectors_in_npy_migration_search_and_reindex` |
| SPEC-KB-18 | `test_spec_kb_vectors.py::test_mixed_index_keeps_semantic_hits_on_top` |
| SPEC-KB-19 | `test_spec_kb_vectors.py::test_kb_search_fuses_org_and_norms_by_rank` |
| SPEC-KB-20 | `test_spec_kb_vectors.py::test_abbreviations_expanded_in_search` |
| SPEC-KB-21 | `test_extras.py::test_tool_aliases_from_registry`, `test_spec_kb_vectors.py::test_recognition_normalizes_writing` |
| SPEC-LLM-01 | `test_extras.py::test_parse_json_truncated_reasoning`, `test_spec_llm_client.py::test_parse_json_cleanup` |
| SPEC-LLM-02 | `test_spec_llm_client.py::test_daily_limit_detection` |
| SPEC-LLM-03 | `test_spec_llm_client.py::test_call_stats_accumulate` |
| SPEC-LLM-04 | `test_spec_llm_client.py::test_disabled_and_budget_guards` |
| SPEC-LLM-05 | `test_spec_llm_client.py::test_success_validates_and_accounts` |
| SPEC-LLM-06 | `test_spec_llm_client.py::test_invalid_json_feedback_then_success` |
| SPEC-LLM-07 | `test_spec_llm_client.py::test_empty_answer_repeats_original` |
| SPEC-LLM-08 | `test_spec_llm_client.py::test_server_errors_retry_then_reserve` |
| SPEC-LLM-09 | `test_spec_llm_client.py::test_auth_error_goes_to_reserve` |
| SPEC-LLM-10 | `test_spec_llm_client.py::test_overload_429_backoff` |
| SPEC-LLM-11 | `test_extras.py::test_daily_limit_fails_fast`, `test_spec_llm_client.py::test_daily_limit_no_retries` |
| SPEC-LLM-12 | `test_spec_llm_client.py::test_judge_role_single_attempt_then_generate` |
| SPEC-LLM-13 | `test_spec_llm_client.py::test_time_budget_exhausted` |
| SPEC-LLM-14 | `test_spec_llm_client.py::test_budget_from_skill_md` |
| SPEC-LLM-15 | `test_extras.py::test_budget_day_is_moscow`, `test_spec_llm_client.py::test_spend_persists_and_resets_daily` |
| SPEC-LLM-16 | `test_spec_llm_client.py::test_spend_write_failure_tolerated` |
| SPEC-LLM-17 | `test_spec_llm_client.py::test_embed_batches` |
| SPEC-LLM-18 | `test_spec_llm_client.py::test_embed_guards` |
| SPEC-LLM-19 | `test_spec_llm_client.py::test_ping` |
| SPEC-LLM-20 | `test_spec_llm_client.py::test_gateway_client_lazy_and_singleton`, `test_spec_llm_client.py::test_gateway_http_errors_and_no_foreign_sdk` |
| SPEC-LLM-21 | `test_spec_robustness.py::test_call_stats_threadsafe_and_merge` |
| SPEC-LLM-22 | `test_spec_robustness.py::test_embed_retries_transient`, `test_spec_robustness.py::test_embed_no_retry_on_auth_and_limit` |
| SPEC-LLM-23 | `test_spec_robustness.py::test_ping_timeout_and_malformed_response` |
| SPEC-LLM-24 | `test_spec_llm_client.py::test_truncated_answer_salvaged_when_partial_ok` |
| SPEC-LLM-25 | `test_spec_llm_client.py::test_budget_checked_after_queue` |
| SPEC-LLM-26 | `test_spec_misc.py::test_llm_status_cache_and_admin_live` |
| SPEC-SVC-01 | `test_spec_service.py::test_new_id_format` |
| SPEC-SVC-02 | `test_spec_service.py::test_save_and_load_roundtrip` |
| SPEC-SVC-03 | `test_spec_service.py::test_missing_program_not_found` |
| SPEC-SVC-04 | `test_spec_service.py::test_snapshots_increment_version` |
| SPEC-SVC-05 | `test_spec_service.py::test_events_with_before_after` |
| SPEC-SVC-06 | `test_spec_service.py::test_notifications_and_mark_read` |
| SPEC-SVC-07 | `test_spec_service.py::test_notify_email_by_profile` |
| SPEC-SVC-08 | `test_spec_service.py::test_send_mail_smtp` |
| SPEC-SVC-09 | `test_spec_service.py::test_head_ids_and_emails` |
| SPEC-SVC-10 | `test_spec_service.py::test_list_programs_filters` |
| SPEC-SVC-11 | `test_spec_service.py::test_jobs_lifecycle` |
| SPEC-SVC-12 | `test_spec_service.py::test_job_failure_recorded` |
| SPEC-SVC-13 | `test_spec_service.py::test_check_capacity` |
| SPEC-SVC-14 | `test_access.py::test_approve_atomic_capacity_first_and_idempotent_job`, `test_spec_service.py::test_start_job_capacity_first_and_idempotent` |
| SPEC-SVC-15 | `test_spec_service.py::test_start_job_capacity_first_and_idempotent` |
| SPEC-SVC-16 | `test_spec_service.py::test_save_survives_malformed_lecture_plan` |
| SPEC-CONTENT-01 | `test_spec_content.py::test_fallback_when_model_disabled` |
| SPEC-CONTENT-02 | `test_spec_content.py::test_fallback_questions` |
| SPEC-CONTENT-03 | `test_spec_content.py::test_fallback_tasks_and_lectures` |
| SPEC-CONTENT-04 | `test_spec_content.py::test_fallback_internship_tasks_every_topic` |
| SPEC-CONTENT-05 | `test_spec_content.py::test_fallback_on_model_error` |
| SPEC-CONTENT-06 | `test_spec_content.py::test_llm_content_mapped` |
| SPEC-CONTENT-07 | `test_spec_content.py::test_llm_tasks_criteria` |
| SPEC-CONTENT-08 | `test_spec_content.py::test_llm_lectures_sources_interview` |
| SPEC-CONTENT-09 | `test_spec_content.py::test_llm_without_tasks_uses_template_tasks` |
| SPEC-CONTENT-10 | `test_spec_content.py::test_llm_request_payload` |
| SPEC-CONTENT-11 | `test_extras.py::test_blocked_services_scrubbed`, `test_spec_content.py::test_blocked_services_removed_from_llm_content` |
| SPEC-CONTENT-12 | `test_spec_content.py::test_scrub_without_blocklist` |
| SPEC-CONTENT-13 | `test_spec_content.py::test_fallback_on_model_error`, `test_spec_content.py::test_code_errors_are_not_swallowed`, `test_spec_robustness.py::test_pptx_slides_when_content_skill_unavailable` |
| SPEC-CONTENT-14 | `test_spec_content.py::test_llm_content_mapped`, `test_spec_content.py::test_llm_invalid_key_not_zeroed` |
| SPEC-CONTENT-15 | `test_spec_content.py::test_element_origin_marked`, `test_spec_repair.py::test_repaired_origin_marked` |
| SPEC-REVIEW-01 | `test_spec_review_assist.py::test_fragment_of` |
| SPEC-REVIEW-02 | `test_spec_review_assist.py::test_fragment_of_zero_index_is_whole_element` |
| SPEC-REVIEW-03 | `test_spec_review_assist.py::test_propose_uses_model` |
| SPEC-REVIEW-04 | `test_spec_review_assist.py::test_propose_fallback` |
| SPEC-REVIEW-05 | `test_spec_review_assist.py::test_propose_full_affected` |
| SPEC-SKILLS-01 | `test_auth.py::test_skill_override_and_reset`, `test_extras.py::test_skills_list_endpoint` |
| SPEC-SKILLS-02 | `test_auth.py::test_skill_override_and_reset` |
| SPEC-SKILLS-03 | `test_auth.py::test_skill_override_and_reset` |
| SPEC-SKILLS-04 | `test_spec_misc.py::test_unknown_skill` |
| SPEC-SKILLS-05 | `test_core.py::test_open_cases_auto` |
| SPEC-SKILLS-06 | `test_e2e_regressions.py::test_intake_direction_from_kurs_po_phrase`, `test_spec_misc.py::test_intake_heuristics_without_llm` |
| SPEC-SKILLS-07 | `test_spec_misc.py::test_classify_type_template_norms_ps` |
| SPEC-SKILLS-08 | `test_spec_misc.py::test_clarify_questions_only_for_missing` |
| SPEC-SKILLS-09 | `test_access.py::test_admin_profile_registry_and_expert_suggestions`, `test_skeleton.py::test_topic_hours_manual_and_assumptions` |
| SPEC-SKILLS-10 | `test_spec_misc.py::test_skeleton_llm_structure_limits` |
| SPEC-SKILLS-11 | `test_skeleton.py::test_match_tf_by_meaning` |
| SPEC-SKILLS-12 | `test_extras.py::test_skeleton_guards` |
| SPEC-SKILLS-13 | `test_e2e_regressions.py::test_fallback_title_not_cut_mid_word`, `test_spec_misc.py::test_skeleton_fallback_library` |
| SPEC-SKILLS-14 | `test_spec_misc.py::test_link_outcomes_both_ways` |
| SPEC-SKILLS-15 | `test_spec_type_detect.py`, `test_spec_type_detect.py::test_type_from_abbreviations_and_audience` |
| SPEC-SKILLS-16 | `test_spec_skill_schemas.py::test_schema_out_matches_models`, `test_spec_skill_schemas.py::test_export_script_check` |
| SPEC-SKILLS-17 | `test_core.py::test_intake_reference_volume_not_program_volume` |
| SPEC-SKILLS-18 | `test_extras.py::test_tool_aliases_from_registry` |
| SPEC-SKILLS-19 | `test_spec_skeleton_domains.py`, `test_spec_skeleton_domains.py::test_postgresql_gets_no_pandas`, `test_spec_skeleton_domains.py::test_docker_exam_task_is_about_docker`, `test_spec_skeleton_domains.py::test_java_reserve_stays_java`, `test_spec_skeleton_domains.py::test_pandas_request_keeps_pandas`, `test_spec_skeleton_domains.py::test_must_covers_only_named_topics` |
| SPEC-SOLVER-01 | `test_core.py::test_largest_remainder_sums` |
| SPEC-SOLVER-02 | `test_spec_solvers.py::test_largest_remainder_deterministic`, `test_spec_solvers.py::test_largest_remainder_tie_break` |
| SPEC-SOLVER-03 | `test_spec_solvers.py::test_round_half_up_not_bankers` |
| SPEC-SOLVER-04 | `test_core.py::test_open_cases_auto`, `test_extras.py::test_adapt_keeps_competencies_and_resolves_hours`, `test_tz_compliance.py::test_solver_property_all_levels` |
| SPEC-SOLVER-05 | `test_core.py::test_open_cases_auto`, `test_tz_compliance.py::test_solver_property_all_levels` |
| SPEC-SOLVER-06 | `test_core.py::test_open_cases_auto`, `test_tz_compliance.py::test_solver_property_all_levels` |
| SPEC-SOLVER-07 | `test_extras.py::test_change_template_before_approval`, `test_tz_compliance.py::test_solver_property_all_levels` |
| SPEC-SOLVER-08 | `test_spec_solvers.py::test_min_practice_reduces_lk_and_srs`, `test_spec_solvers.py::test_min_practice_unreachable_note` |
| SPEC-SOLVER-09 | `test_spec_solvers.py::test_solver_takes_only_weights_and_shares` |
| SPEC-SOLVER-10 | `test_spec_solvers.py::test_calendar_by_sessions` |
| SPEC-SOLVER-11 | `test_spec_solvers.py::test_calendar_by_days` |
| SPEC-SOLVER-12 | `test_spec_solvers.py::test_calendar_conflict_and_options` |
| SPEC-SOLVER-13 | `test_spec_solvers.py::test_calendar_apply_option_recomputes` |
| SPEC-SOLVER-14 | `test_skeleton.py::test_calendar_kinds_and_lecture_plans` |
| SPEC-SOLVER-15 | `test_spec_solvers.py::test_recompute_is_fast_and_offline` |
| SPEC-SOLVER-16 | `test_spec_solvers.py::test_calendar_conflict_strict_capacity` |
| SPEC-JUDGE-01 | `test_spec_judge.py::test_judge_skipped_when_disabled` |
| SPEC-JUDGE-02 | `test_spec_judge.py::test_judge_call_parameters` |
| SPEC-JUDGE-03 | `test_spec_judge.py::test_view_is_compact` |
| SPEC-JUDGE-04 | `test_spec_judge.py::test_only_warn_with_messages_kept`, `test_spec_judge.py::test_verdict_node_tagged` |
| SPEC-JUDGE-05 | `test_spec_judge.py::test_judge_failure_keeps_code_results` |
| SPEC-JUDGE-06 | `test_spec_judge.py::test_merge_adds_judge_messages` |
| SPEC-JUDGE-07 | `test_spec_judge.py::test_view_contains_real_materials`, `test_spec_judge.py::test_judge_receives_materials`, `test_spec_judge.py::test_view_truncates_materials`, `test_spec_judge.py::test_view_module_budget` |
| SPEC-JUDGE-08 | `test_spec_judge.py::test_judge_rows_separate_from_code`, `test_spec_judge.py::test_audit_counterexample_is_caught` |
| SPEC-REPAIR-01 | `test_spec_repair.py::test_no_failed_rules_no_changes` |
| SPEC-REPAIR-02 | `test_spec_repair.py::test_v19_duplicates_removed_and_key_fixed` |
| SPEC-REPAIR-03 | `test_spec_repair.py::test_v19_key_keeps_correct_answer` |
| SPEC-REPAIR-04 | `test_spec_repair.py::test_v18_rubric_added` |
| SPEC-REPAIR-05 | `test_spec_repair.py::test_v14_bindings_to_existing_outcomes` |
| SPEC-REPAIR-06 | `test_spec_repair.py::test_v14_choice_is_deterministic_across_processes` |
| SPEC-REPAIR-07 | `test_spec_repair.py::test_v13_final_and_question_cover_outcome` |
| SPEC-REPAIR-08 | `test_spec_repair.py::test_cover_outcomes_question_shape` |
| SPEC-REPAIR-09 | `test_spec_repair.py::test_cover_outcomes_final_test_and_seminar` |
| SPEC-REPAIR-10 | `test_spec_repair.py::test_cover_outcomes_replaces_spare_when_volume_fixed` |
| SPEC-REPAIR-11 | `test_spec_repair.py::test_v09_lecture_titles_and_slides` |
| SPEC-REPAIR-12 | `test_spec_repair.py::test_v09_respects_requested_modules_with_slides` |
| SPEC-REPAIR-13 | `test_spec_repair.py::test_v17_reference_overlap_removed` |
| SPEC-REPAIR-14 | `test_spec_repair.py::test_v17_without_reference_noop` |
| SPEC-REPAIR-15 | `test_spec_repair.py::test_v08_v11_sections_rebuilt` |
| SPEC-REPAIR-16 | `test_spec_repair.py::test_v16_unconfirmed_sources_marked_once` |
| SPEC-REPAIR-17 | `test_spec_repair.py::test_v19_key_restored_by_text_only` |
| SPEC-REPAIR-18 | `test_spec_repair.py::test_v13_final_task_text_extended_for_added_lo`, `test_spec_repair.py::test_v13_seminar_task_text_extended_for_added_lo` |
| SPEC-RULES-01 | `test_spec_rules.py::test_27_rules_kinds` |
| SPEC-RULES-02 | `test_spec_rules.py::test_stage_rule_sets` |
| SPEC-RULES-03 | `test_spec_rules.py::test_fail_downgraded_and_exception_isolated` |
| SPEC-RULES-04 | `test_access.py::test_auto_async_returns_202_and_job_result`, `test_core.py::test_open_cases_auto` |
| SPEC-RULES-05 | `test_core.py::test_open_cases_auto` |
| SPEC-RULES-06 | `test_spec_rules.py::test_v05_v06_v07_hours_rules` |
| SPEC-RULES-07 | `test_spec_rules.py::test_v08_v09_completeness` |
| SPEC-RULES-08 | `test_spec_rules.py::test_v10_calendar` |
| SPEC-RULES-09 | `test_spec_rules.py::test_v11_human_fields`, `test_spec_rules.py::test_v11_staff_section` |
| SPEC-RULES-10 | `test_spec_rules.py::test_v12_v13_coverage` |
| SPEC-RULES-11 | `test_spec_rules.py::test_v14_binding` |
| SPEC-RULES-12 | `test_spec_rules.py::test_v15_v16_sources` |
| SPEC-RULES-13 | `test_spec_rules.py::test_v17_originality` |
| SPEC-RULES-14 | `test_spec_rules.py::test_v18_v19_measurability` |
| SPEC-RULES-15 | `test_skeleton.py::test_decisions_per_node` |
| SPEC-RULES-16 | `test_spec_rules.py::test_warning_only_rules` |
| SPEC-RULES-17 | `test_skeleton.py::test_topic_hours_manual_and_assumptions`, `test_skeleton.py::test_decisions_per_node` |
| SPEC-RULES-18 | `test_spec_rules.py::test_coverage_matrix_planned_and_actual` |
| SPEC-RULES-19 | `test_spec_rules.py::test_originality_by_8grams` |
| SPEC-RULES-20 | `test_core.py::test_open_cases_auto` |
| SPEC-RULES-21 | `test_spec_rules.py::test_v26_latin_share_per_node` |
| SPEC-RULES-23 | `test_spec_rules.py::test_v16_registry_freshness_warn` |
| SPEC-RULES-22 | `test_spec_rules.py::test_v18_v25_material_quality` |
| SPEC-SANDBOX-01 | `test_spec_sandbox.py::test_empty_code_skipped` |
| SPEC-SANDBOX-02 | `test_spec_sandbox.py::test_system_access_not_run`, `test_spec_sandbox.py::test_legit_examples_still_run` |
| SPEC-SANDBOX-03 | `test_spec_sandbox.py::test_heavy_libraries_syntax_only` |
| SPEC-SANDBOX-04 | `test_spec_sandbox.py::test_libraries_detected_in_order` |
| SPEC-SANDBOX-05 | `test_spec_sandbox.py::test_run_success_stdout_and_input` |
| SPEC-SANDBOX-06 | `test_spec_sandbox.py::test_run_error_last_stderr_line` |
| SPEC-SANDBOX-07 | `test_spec_sandbox.py::test_network_is_blocked` |
| SPEC-SANDBOX-08 | `test_spec_sandbox.py::test_timeout_reported` |
| SPEC-SANDBOX-09 | `test_spec_sandbox.py::test_run_snippet` |
| SPEC-SANDBOX-10 | `test_spec_sandbox.py::test_check_examples_limit_and_messages` |
| SPEC-SANDBOX-11 | `test_spec_sandbox.py::test_limits_from_settings` |
| SPEC-SANDBOX-12 | `test_spec_sandbox.py::test_limits_degrade_on_macos` |
<!-- trace:end -->
