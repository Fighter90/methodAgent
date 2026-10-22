# Ответ на повторный аудит 22.10 (R01–R19)

База аудита: коммит `f1cc53d`. Ниже — статус каждого пункта после волн исправлений 22.10 (коммиты `a2d2aa7`…`63e8de1` и далее). Детали — в задачах Linear (MET-45…63) и тестах с ID `SPEC-*`.

| Пункт | Статус | Что сделано | Где проверено |
|---|---|---|---|
| R01 изоляция песочницы | частично (усилено) | AST-слой разрешённых импортов + запрет dunder-доступа (SPEC-SANDBOX-14); лимиты FSIZE/CORE; отчёт applied/skipped_limits. Полная изоляция — отдельный исполнитель, план в MET-45 | `test_spec_sandbox.py::test_ast_allowlist_blocks_escape_vectors` |
| R02 агрегатные ссылки + actualize | выполнено | `_resolve_node` разрешает все формы (включая тесты), неизвестный id → 404; actualize фильтруется по модулям эксперта | `test_expert_cannot_touch_foreign_aggregates`, `test_expert_actualize_hides_foreign_modules` |
| R03 атомарность заданий | выполнено | повторное чтение активного задания в транзакции; параллельные approve → один job | `test_start_job_parallel_reserves_single_job`, `test_parallel_approve_creates_exactly_one_job` |
| R04 возврат при утверждённой | выполнено | return вне шагов каркаса → 409 BAD_STATE | `test_return_rejected_for_approved_program` |
| R05 предмет финального задания | в работе | workflow-агент: builder от предмета каркаса | MET-49 |
| R06 частичный ответ ≠ done | в работе | origin элементов внедрён (SPEC-CONTENT-15); статусы по полноте — MET-50 | `test_element_origin_marked` |
| R07 мета-вопрос | выполнено | предметный вопрос из РО с командными дистракторами; метапостановка не считается средством V-13 (SPEC-REPAIR-19/20) | `test_cover_outcomes_subject_question_with_commands`, `test_v13_meta_question_not_counted_as_mean` |
| R08 судья видит финал/тела | выполнено | блок итоговой аттестации, тела ModuleProgram порциями, строка покрытия (SPEC-JUDGE-09…12) | `test_final_swap_is_visible_to_judge`, `test_view_contains_module_program_bodies` |
| R09 поля формы | в работе | backend: params приоритетно над текстом, конфликты в assumptions (SPEC-API-39); фронт: отправка структуры — MET-53 | `test_form_params_override_text_with_conflict_note` |
| R10 роли чисел объёма | выполнено | «с X до Y», роль по слову программы; референс не участвует в max (SPEC-SKILLS-20) | `test_intake_volume_roles_with_reference` |
| R11 домен ≠ подтверждение | в работе | уровни «открывается/доверенный/метаданные» — MET-55 | частично: чужой домен уже не подтверждает |
| R12 SSRF фильтра | в работе | URL-парсер, userinfo, редиректы — MET-56 | частично: локальные хосты отсекаются |
| R13 quality_report | выполнено | returncode и структурированные вердикты; exit 1 при провале (SPEC-Q-01) | `test_quality_report.py` (5 тестов) |
| R14 слайды по принадлежности | выполнено | чек полноты тем pandas и принадлежности модулям (SPEC-Q-02) | `test_case3_slides_check_requires_every_pandas_topic` |
| R15 браузерный CI | выполнено | playwright закреплён в e2e/package.json, задача блокирующая | локальный прогон 93/93 без глобальных пакетов |
| R16 бюджет ping/embed, штамп кэша | выполнено | бюджет до каждого сетевого вызова; учёт стоимости ping; объединение проверок под Lock (SPEC-LLM-27/28) | `test_ping_budget_and_spend`, `test_llm_status_stampede_single_ping` |
| R17 ремап prerequisites | в работе | workflow-агент: идентичность тем при сортировке | MET-61 |
| R18 таблицы DOCX в контексте | выполнено | абзацы и таблицы в исходном порядке, вложенные таблицы (SPEC-KB-22) | `test_docx_tables_in_reference_text` |
| R19 PDF с паролем → 400 | выполнено | needs_pass до чтения, битый PDF → 400 (SPEC-KB-23) | `test_pdf_encrypted_rejected_and_plain_ok` |

Регресс на момент ответа: 368+ pytest, 50 vitest, 1381 API e2e, 93 UI e2e, глубокий обход без ошибок.
