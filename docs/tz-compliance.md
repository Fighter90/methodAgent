# Сверка с ТЗ: матрица соответствия

Документ сверяет код МетодАгента с требованиями технического задания пункт за пунктом. Сверка проведена 19.10.2026 на рабочем дереве репозитория (после коммита `25a342b` и параллельных правок `e2e_regression`). Краткая сводка для wiki: [Соответствие ТЗ](../wiki/Соответствие-ТЗ.md).

## Источники и метод

Сверялись четыре документа:

1. Бриф кейса «ИИ-агент для создания образовательных программ» (задача № 1 хакатона): требования раздела 5 «Формат решения», ограничения раздела 4, целевой сценарий раздела 3. В брифе нет нумерации FR и NFR, поэтому его требования сверены через таблицу Б.1 ТЗ (строки К-01…К-32 ниже).
2. Техническое задание «МетодАгент», версия 2.0 от 17.10.2026 (`МетодАгент_ТЗ.docx` из материалов проекта): роли, пользовательские истории US-01…US-24, функциональные требования FR-01…FR-63, интерфейс, навыки, солвер, правила V-01…V-27, модель данных 4.8, API 4.9 с контрактом автопрогона, NFR-01…NFR-16, стек 4.11, метрики Q-01…Q-26, критерии приёмки 6.4.
3. Открытые тест-кейсы с эталонными чек-листами (5 запросов и общие требования, 51 пункт).
4. Образцы программ АЦР: ДПП ПК в форме стажировки «Бизнес и системный анализ» (248 ч) и ДООП «Интенсив по созданию продуктов на основе ИИ» (24 ч).

Как проверялось:

- полный прогон `PYTHONPATH=src pytest -q --cov=src/app` (тесты не ходят в сеть, `LLM_PROVIDERS=fixtures`); ссылки на тесты даны в виде `файл::функция`;
- автопрогон пяти открытых кейсов через `POST /api/v1/programs?mode=auto` на детерминированных ответах навыков, выгрузка всех семи форматов по каждому кейсу;
- три синтетических запроса (ДПП ПК 500 ч, ДООП 24 ч, ДПП ПК 16 ч) тем же путём;
- сравнение сгенерированных DOCX с образцами АЦР по заголовкам, порядку разделов и шапкам таблиц (раздел «Сверка DOCX с шаблонами АЦР»);
- чтение кода: ссылки вида `файл:строка` или `файл (функция)`, если строки сдвигаются параллельными правками.

Ограничение сверки: живой прогон на моделях Cloud.ru из этой среды не выполнялся, поэтому требования ко времени и стоимости на реальной модели помечены «частично», даже если бюджеты и учёт заложены в код.

Статусы: **выполнено**, **частично** (сделано не полностью или с отступлением от буквы ТЗ, причина указана), **не выполнено**.

## Сводка

| Раздел | Строк | Выполнено | Частично | Не выполнено |
|---|---|---|---|---|
| Требования брифа кейса (К-01…К-32) | 32 | 28 | 4 | 0 |
| 1.5 Порядок предъявления результатов | 5 | 4 | 1 | 0 |
| 4.1 Роли и права | 7 | 7 | 0 | 0 |
| 4.2 Пользовательские истории | 24 | 20 | 4 | 0 |
| 4.3 Функциональные требования | 63 | 58 | 5 | 0 |
| 4.4 Интерфейс: экраны и правила блокировки | 20 | 20 | 0 | 0 |
| 4.5 Навыки агента | 12 | 9 | 3 | 0 |
| 4.6 Алгоритм распределения часов | 6 | 6 | 0 | 0 |
| 4.7 Правила автопроверки | 28 | 26 | 2 | 0 |
| 4.8 Модель данных и JSON | 19 | 19 | 0 | 0 |
| 4.9 API: методы, ошибки, автопрогон | 38 | 36 | 2 | 0 |
| 4.10 Нефункциональные требования | 16 | 10 | 6 | 0 |
| 4.11 Архитектура, стек, безопасность, разработка | 26 | 19 | 7 | 0 |
| 5 Метрики качества | 26 | 14 | 8 | 4 |
| 6.4 Критерии приёмки | 8 | 3 | 3 | 2 |
| Чек-листы открытых тест-кейсов | 51 | 45 | 6 | 0 |
| **Итого** | **381** | **324** | **51** | **6** |

Все «не выполнено» относятся к метрикам пилота, для которых нужны эксперты, слушатели или золотой набор (Q-14, Q-16, Q-20, Q-24), и к замерам с методистом на живом комплекте (ПР-07, ПР-08). Функциональных требований со статусом «не выполнено» нет.

## Требования брифа кейса (таблица Б.1 ТЗ)

| № | Требование брифа | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| К-01 | Оба шаблона АЦР, любое ИТ-направление, объём 16…500 ч | выполнено | `test_core.py::test_open_cases_auto` (16, 36, 72, 72, 256 ч), синтетические запуски 500, 24 и 16 ч: статус `done`, 10/10 | |
| К-02 | Приём запроса и референсов в .docx, .pdf и тексте | выполнено | `kb/files.py:29` (тип по сигнатуре), `test_skeleton.py::test_pdf_reference_hours_checked`, `test_extras.py::test_cyrillic_txt_cut_at_2000_bytes_is_text` | |
| К-03 | Уточняющие вопросы | выполнено | `skills/clarify/run.py (run)`, `test_spec_misc.py::test_clarify_questions_only_for_missing`; кейс 4: пять вопросов | |
| К-04 | Карта компетенций: компетенция, З/У/Н, темы, вопросы, задания | выполнено | граф в `programs/schemas.py`, правила V-12…V-14, `test_spec_rules.py::test_coverage_matrix_planned_and_actual` | |
| К-05 | Учебный план и УТП с часами по видам работы и проверкой сумм | выполнено | `solver/hours.py (solve)`, V-01…V-07, `test_tz_compliance.py::test_solver_property_all_levels` | |
| К-06 | Тестовые вопросы с ключами и привязкой к РО | выполнено | V-14, V-19, `test_spec_rules.py::test_v18_v19_measurability` | |
| К-07 | Задания семинаров с критериями оценки | выполнено | V-18, `test_spec_content.py::test_llm_tasks_criteria` | |
| К-08 | Планы лекций и слайды .pptx хотя бы для одного модуля | выполнено | `export/service.py (render_pptx)`, `test_spec_export.py::test_pptx_16x9_and_fallback`, V-09 | |
| К-09 | Выгрузка программы .docx по шаблону АЦР | выполнено | `export/service.py:250` (render_docx), раздел «Сверка DOCX с шаблонами АЦР» | |
| К-10 | Отчёт автопроверки по часам, покрытию, источникам и полноте разделов | выполнено | `validation/report.py:100`, `GET /programs/{id}/report` | |
| К-11 | Точечная доработка без пересборки всего комплекта | выполнено | `agent/workflow.py (edit, descendants)`, `test_spec_misc.py::test_edit_rollback_and_new_version` | |
| К-12 | Выгрузка тестов в LMS (GIFT, Moodle XML или CSV) | выполнено | `test_spec_export.py::test_gift_and_moodle_xml` | |
| К-13 | Актуализация старой программы | выполнено | `agent/extras.py:134` (scan_text), `test_extras.py::test_actualize_text_and_program` | |
| К-14 | Адаптация под другую аудиторию или объём | выполнено | `agent/extras.py:63` (adapt), `test_extras.py::test_adapt_keeps_competencies_and_resolves_hours` | |
| К-15 | Только модели Cloud.ru Evolution Foundation Models | выполнено | `core/config.py` (адрес `foundation-models.api.cloud.ru`, модели GigaChat), в зависимостях нет SDK зарубежных провайдеров; SDK `openai` используется только как клиент OpenAI-совместимого API | |
| К-16 | Единый API-эндпоинт для проверки | выполнено | `POST /api/v1/programs?mode=auto`, `programs/router.py (create_program)` | |
| К-17 | Шаги агента как навыки с инструкцией | выполнено | 11 каталогов `skills/*/` с `SKILL.md`, `schema_in.json` и `schema_out.json`; выходные схемы генерируются из моделей результата (`skills/outputs.py`, `scripts/export_skill_schemas.py --check`), `test_spec_skill_schemas.py::test_schema_out_matches_models` | |
| К-18 | Каркас до 3 мин, комплект 72 ч до 20 мин | частично | бюджеты времени навыков из SKILL.md (`test_spec_llm_client.py::test_budget_from_skill_md`), `timing_s` в ответе; на fixtures каркас и комплект меньше 1 с | замера на живой модели Cloud.ru нет |
| К-19 | Человек утверждает цель, компетенции и часы до содержания | выполнено | `agent/workflow.py (approve_skeleton, generate_kit)`, `test_spec_misc.py::test_generate_requires_approved_skeleton` | |
| К-20 | Реквизиты приказа, ФИО, подписи остаются полями | выполнено | V-11 (`validation/rules.py:263`, теперь и раздел 3.4), `test_spec_export.py::test_human_fields_left_blank` | |
| К-21 | Любая часть переделывается без нарушения согласованности | выполнено | V-20, откат `EDIT_REJECTED`, `test_spec_misc.py::test_edit_rollback_and_new_version` | |
| К-22 | ПК: 273-ФЗ, приказ № 499, ПС и коды ТФ; ДООП: приказ № 629 | частично | `test_spec_misc.py::test_classify_type_template_norms_ps`, `test_norms.py::test_repealed_acts_are_not_used` | вместо приказа № 499 указывается действующий приказ Минобрнауки от 24.03.2025 № 266 (№ 499 утратил силу с 01.09.2025); отступление сознательное |
| К-23 | Русский язык; выгрузка .docx, .pptx и JSON | выполнено | `export/service.py:30` (FORMATS), V-26 | |
| К-24 | Нет выдуманных источников, неподтверждённые помечены | выполнено | `agent/workflow.py (_sources, check_source_urls)`, V-15, V-16, `test_spec_misc.py::test_sources_confirmed_or_marked` | |
| К-25 | Нет дословного копирования референсов | выполнено | V-17 по 8-граммам, `test_spec_repair.py::test_v17_reference_overlap_removed` | |
| К-26 | Не один промпт: отдельные шаги структуры, содержания и проверки | выполнено | навыки intake, classify, clarify, skeleton, hours_solver, content, validate, repair, export | |
| К-27 | Защита: каркас в реальном времени и эффект в часах и токенах | частично | прогресс задания и `timing_s`, блок `effect` в ответе автопрогона и карточке программы (`agent/workflow.py (effect)`), `tokens.cost_rub` | цифры эффекта и стоимости на живой модели не замерены |
| К-28 | Методист проверяет и решает, а не делает рутину | выполнено | решения по пунктам «!» (`decide`), `test_skeleton.py::test_decisions_per_node` | |
| К-29 | Эксперт проверяет содержание и вычитывает лекции | выполнено | вычитка по модулям, `test_access.py::test_expert_sees_only_own_modules_and_accepts_items` | |
| К-30 | Руководитель утверждает программу | выполнено | `test_spec_misc.py::test_submit_and_head_decision` | |
| К-31 | Меньше повторных согласований | выполнено | журнал и уведомления, `test_spec_service.py::test_events_with_before_after` | |
| К-32 | Документы организации и других организаций | частично | режим «Документы организации», `test_extras.py::test_kb_upload_and_search` | эмбеддинги Giga-Embeddings вместо bge-m3, реранкера нет (см. FR-09) |

## 1.5 Порядок предъявления результатов

| № | Требование | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| П-01 | Код в репозитории команды, проверяется последний коммит main | выполнено | репозиторий команды в Gitea, ветка main с историей коммитов; вики проекта в Gitea | |
| П-02 | Сервис на ВМ, порт 8000: интерфейс и единый эндпоинт | выполнено | `docker-compose.yml` (порт 8000), `Dockerfile` (HEALTHCHECK `/health`), `scripts/run_vm.sh` | |
| П-03 | Документация: ТЗ, макеты, файл расчётов, протокол испытаний | частично | `README.md`, `docs/`, `wiki/`, `specs/` | в репозитории нет ТЗ, макетов, `МетодАгент_расчёты.xlsx` и протокола испытаний по разделу 6 |
| П-04 | README с запуском и ссылками | выполнено | `README.md` (запуск, документация, пример `curl` автопрогона) | |
| П-05 | Демо-стенд | выполнено | `README.md:12` (https://methodagent.ru) | |

## 4.1 Роли, права и матрица ответственности

| № | Требование | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| Р-01 | Методист: запрос, вопросы, каркас, правка, эксперты, отправка; не утверждает программу | выполнено | `require('methodist')` на методах `programs/router.py`, `test_core.py::test_roles` | |
| Р-02 | Эксперт: только свои модули, часы и шаблон только для чтения | выполнено | `programs/router.py (expert_view, _load_for)`, `test_access.py::test_unassigned_expert_cannot_accept_and_api_404` | |
| Р-03 | Руководитель: утверждает только при готовности 100 %, не правит содержание | выполнено | `agent/workflow.py (head_decision)`, код `NOT_READY` | |
| Р-04 | Администратор: шаблоны, документы, реестр, пользователи, роли и токены API; не работает с программами | выполнено | `/admin/*`, `/org/*`, `test_auth.py::test_admin_manages_users_but_not_programs`; токены API: `POST/GET /admin/api-tokens`, `DELETE /admin/api-tokens/{id}` (`auth/tokens.py`, в базе только SHA-256, отозванный токен — 401), вкладка «Токены API» в `Admin.tsx`, `test_spec_tokens.py::test_admin_issues_lists_and_revokes_api_tokens` | |
| Р-05 | API-клиент: только свои задания, в auto полный комплект, не утверждает | выполнено | `programs/router.py (_load_for)`, `test_access.py::test_no_token_cannot_read_others` | |
| Р-06 | Несколько ролей у пользователя и переключатель | выполнено | `/auth/switch-role`, `/me/tasks`, `test_extras.py::test_sandbox_and_tasks` | |
| Р-07 | Права на каждом вызове API, вне прав 403 (RACI, таблица 7) | выполнено | `core/security.py (require)`, `test_auth.py::test_admin_manages_users_but_not_programs` | |

## 4.2 Пользовательские истории

| № | История (кратко) | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| US-01 | Запрос текстом и референсы, панель параметров, пересчёт часов референса | выполнено | FR-01…FR-05 | |
| US-02 | Агент выбирает шаблон и нормативную базу | частично | FR-06…FR-10 | № 266 вместо № 499; FR-09 частично |
| US-03 | Только недостающие вопросы, до 5 | выполнено | FR-11…FR-13 | |
| US-04 | Каркас за 3 минуты | частично | FR-14…FR-19 | нет живого замера (FR-19) |
| US-05 | Правка часов с пересчётом за 1 с | выполнено | FR-17, `test_spec_solvers.py::test_recompute_is_fast_and_offline` | |
| US-06 | Утверждение каркаса после проверки | выполнено | FR-20…FR-24 | |
| US-07 | Комплект 72 ч за 20 минут с прогрессом и стоимостью | частично | FR-25…FR-31 | нет живого замера; шлюз пропускает 2 запроса одновременно |
| US-08 | Отчёт автопроверки, блокировка вычитки | выполнено | FR-32…FR-35 | |
| US-09 | Замена темы или усложнение теста без пересборки | выполнено | FR-36…FR-38 | |
| US-10 | Назначение экспертов и контроль вычитки | выполнено | FR-39…FR-43 | |
| US-11 | Эксперт видит свои модули и РО элементов | выполнено | FR-44, FR-45 | |
| US-12 | Примеры кода проверены в песочнице | выполнено | FR-46 | |
| US-13 | Комментарий к фрагменту и правка агентом после подтверждения | выполнено | FR-47, FR-48, `test_tz_compliance.py::test_expert_comment_proposal_needs_expert_confirmation` | |
| US-14 | Принять модуль или вернуть методисту | выполнено | FR-49 | |
| US-15 | Уведомления о назначении, ответах и изменении принятого модуля | выполнено | `test_tz_compliance.py::test_changed_accepted_module_returns_to_review_and_notifies_expert` (уведомление об изменении принятого модуля добавлено в этой сверке) | |
| US-16 | Страница готовности руководителя | выполнено | FR-50, FR-51 | |
| US-17 | Утверждение и проект приказа без реквизитов | выполнено | FR-52, FR-54 | |
| US-18 | Возврат с обязательным комментарием | выполнено | FR-53 | |
| US-19 | Программы на утверждении и утверждённые за период | выполнено | `test_extras.py::test_head_filter` | |
| US-20 | Загрузка шаблонов и положений организации | частично | FR-08, FR-09 | версия профиля фиксируется только датой `checked_at`; эмбеддинги не bge-m3 |
| US-21 | Реестр ПС, НПА и версий с датой проверки | выполнено | FR-10, `PUT /org/registry`, журнал `org_registry` | |
| US-22 | Пользователи, роли и токены API | выполнено | `/admin/users`, `/admin/api-tokens` (выдача со сроком, список без секретов, отзыв), `test_spec_tokens.py::test_admin_issues_lists_and_revokes_api_tokens`, `test_spec_tokens.py::test_expired_api_token_rejected` | |
| US-23 | Автопрогон одним запросом | выполнено | FR-62 | |
| US-24 | Внешняя система забирает результат по API | выполнено | `GET /jobs/{id}`, выгрузки по форматам, ошибки JSON на русском | |

## 4.3 Функциональные требования

| № | Требование (кратко) | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| FR-01 | Запрос текстом до 5 000 символов | выполнено | `programs/router.py:63` (`max_length=5000`), `test_spec_misc.py::test_request_limits` | |
| FR-02 | .docx, .pdf, текст; до 5 файлов, до 20 МБ | выполнено | `programs/router.py (_parse_files)`, `kb/files.py:29`, `test_spec_misc.py::test_request_limits` | |
| FR-03 | Распознанные параметры в панели | выполнено | `skills/intake/run.py (parse_numbers, run)`, экран `Program.tsx` («Распознанные параметры»), `test_spec_misc.py::test_intake_heuristics_without_llm` | |
| FR-04 | Из референса только структура, 8-граммы меньше 5 % | выполнено | V-17, `test_spec_rules.py::test_v17_originality` | |
| FR-05 | Пересчёт таблиц часов референса, ошибки не переносятся | выполнено | `kb/files.py (check_hours_table)`, заметка агента в кейсах 3 и 5 (12 расхождений образца), `test_skeleton.py::test_pdf_reference_hours_checked` | |
| FR-06 | Тип программы и шаблон, смена до утверждения | выполнено | `skills/classify/run.py:28`, `POST /programs/{id}/template`, `test_extras.py::test_change_template_before_approval` | |
| FR-07 | 273-ФЗ, приказ № 499, ПС из реестра; ДООП: № 629 без ПС | частично | `test_spec_misc.py::test_classify_type_template_norms_ps`, кейс 1: `ps_code = null` | приказ № 266 вместо утратившего силу № 499 |
| FR-08 | Режимы «Госстандарты» и «Документы организации» | выполнено | `norm_mode`, `agent/extras.py:341`, `test_spec_misc.py::test_norm_and_org_fragments` | |
| FR-09 | Документы организации в базе знаний (bge-m3, реранкер) со ссылкой | частично | `kb/orgdocs.py:88`, `test_extras.py::test_kb_upload_and_search` | эмбеддинги Giga-Embeddings через шлюз, без модели поиск по словам; реранкера нет |
| FR-10 | Реестр ПС, НПА, версий с датой проверки; вне реестра «не подтверждено» | выполнено | `registry/*.json`, `kb/registry.py`, `test_norms.py::test_profstandards_for_cases` | |
| FR-11 | Вопросы при пустом обязательном поле, каркас не строится до ответов | выполнено | `skills/clarify/run.py:58`, статус `questions`, `QUESTIONS_PENDING` | |
| FR-12 | До 5 вопросов, без жаргона, с вариантами и своим ответом | выполнено | `test_spec_misc.py::test_clarify_questions_only_for_missing`, кейс 4 | |
| FR-13 | «На ваше усмотрение» заполняет значением профиля с пометкой | выполнено | `skills/clarify/run.py:43`, `assumptions`, `test_skeleton.py::test_topic_hours_manual_and_assumptions` | |
| FR-14 | Цель и компетенции З/У/Н, связь с ТФ | выполнено | `test_skeleton.py::test_match_tf_by_meaning` | |
| FR-15 | УП и УТП, часы по видам, суммы на всех уровнях | выполнено | `test_tz_compliance.py::test_solver_property_all_levels` | |
| FR-16 | Часы считает детерминированный солвер | выполнено | `test_spec_solvers.py::test_solver_takes_only_weights_and_shares` | |
| FR-17 | Правка часов, названий, формулировок; пересчёт до 1 с | выполнено | `PATCH /skeleton`, `test_spec_solvers.py::test_recompute_is_fast_and_offline` | |
| FR-18 | Календарный график, варианты при конфликте | выполнено | `solver/calendar.py:34`, `test_spec_solvers.py::test_calendar_conflict_and_options` | |
| FR-19 | Каркас 16…500 ч не дольше 180 с | частично | бюджеты навыков, `timing_s.skeleton` | нет замера на живой модели |
| FR-20 | Проверка каркаса ✓ / ! / ✕ | выполнено | `validation/rules.py:19` (SKELETON_RULES), `test_spec_rules.py::test_stage_rule_sets` | |
| FR-21 | При ✕ утвердить нельзя | выполнено | `SKELETON_HAS_ERRORS`, `test_spec_misc.py::test_approve_skeleton_errors_and_pending` | |
| FR-22 | Решение по каждому «!», запись в журнал | выполнено | `POST /skeleton/decisions`, `test_skeleton.py::test_decisions_per_node` | |
| FR-23 | Генерация только после утверждения или auto-approve | выполнено | `SKELETON_NOT_APPROVED`, `test_tz_compliance.py::test_auto_calendar_choice_refreshes_skeleton_report` | |
| FR-24 | Возврат каркаса с комментарием и перестройка | выполнено | `test_spec_misc.py::test_return_with_comment_passes_current_skeleton` | |
| FR-25 | Программа по разделам шаблона (ДПП ПК 19 разделов) и рабочие программы | выполнено | `validation/rules.py:26` (SECTIONS_DPP, 26 разделов и 2 приложения), V-08 | |
| FR-26 | Тесты: один ключ, дистракторы, ID РО, точное число вопросов | выполнено | V-09, V-19, кейс 1: ровно 10 вопросов | |
| FR-27 | Задания: условие, результат, критерии, баллы, РО | выполнено | `test_spec_content.py::test_llm_tasks_criteria` | |
| FR-28 | Планы лекций с хронометражем, слайды для модулей из запроса | выполнено | `test_skeleton.py::test_calendar_kinds_and_lecture_plans`, `test_spec_repair.py::test_v09_respects_requested_modules_with_slides` | |
| FR-29 | Литература проверяется по реестру или ссылке | выполнено | `agent/workflow.py (check_source_urls)`, `test_spec_misc.py::test_sources_confirmed_or_marked` | |
| FR-30 | Параллельно по модулям, не меньше 4 потоков (6), прогресс, токены | частично | `agent/workflow.py (generate_kit)`: `workers = max(4, gen_workers)`, прогресс с `eta_s` и токенами | к шлюзу одновременно идут только 2 запроса (`llm_concurrency = 2`, ограничение шлюза хакатона) |
| FR-31 | Комплект 72 ч не дольше 1 200 с | частично | `timing_s.kit` | нет замера на живой модели |
| FR-32 | 27 правил: 23 кодом, 4 судьёй | выполнено | `validation/rules.py:486`, `test_spec_rules.py::test_27_rules_kinds` | |
| FR-33 | Отчёт: каждое правило, матрица РО × средство, действия | выполнено | `validation/report.py:100`, SPEC-RULES-17 | |
| FR-34 | repair до 2 попыток, остаток методисту | выполнено | `agent/workflow.py (generate_kit)`, `test_spec_repair.py` | |
| FR-35 | Без 10/10 нельзя на вычитку и утверждение | выполнено | `BLOCKING_FAILED` в `assign_expert` и `submit` | |
| FR-36 | Правка с «было / станет» и списком затрагиваемых | выполнено | `dry_run`, `test_access.py::test_edit_hours_keeps_module_total_and_text_edit_finds_target` | |
| FR-37 | Пересобираются только потомки, затем полная проверка | выполнено | `agent/workflow.py (descendants, edit)`, `test_spec_misc.py::test_edit_rollback_and_new_version` | |
| FR-38 | Версии, сравнение, откат | выполнено | `test_extras.py::test_versions_diff_and_sections`, `test_access.py::test_restore_does_not_bring_back_approval` | |
| FR-39 | Назначение экспертов, подсказка из профиля | выполнено | `agent/extras.py:369`, `test_access.py::test_admin_profile_registry_and_expert_suggestions` | |
| FR-40 | Экран «Согласование» со статусами | выполнено | `Program.tsx`, статусы `not_started/in_review/question/accepted/returned` | |
| FR-41 | Вопрос эксперта передаётся агенту или методист отвечает сам | выполнено | `POST /comments/answer` (`ask_agent`), `test_spec_review_assist.py::test_propose_full_affected` | |
| FR-42 | Отправка при всех принятых модулях и 10/10 | выполнено | `MODULES_NOT_ACCEPTED`, `test_spec_misc.py::test_submit_and_head_decision` | |
| FR-43 | Изменение принятого модуля возвращает его на вычитку | выполнено | `agent/workflow.py (edit)`, `test_tz_compliance.py::test_changed_accepted_module_returns_to_review_and_notifies_expert` | |
| FR-44 | Эксперт видит только свои модули | выполнено | `test_access.py::test_expert_sees_only_own_modules_and_accepts_items` | |
| FR-45 | У элементов показаны РО и средства проверки | выполнено | `lo_ids` у вопросов, заданий, тем; экран вычитки | |
| FR-46 | Песочница: результат, версия, время, устаревшее | выполнено | `GET /programs/{id}/sandbox`, `test_spec_sandbox.py` | |
| FR-47 | Комментарий к фрагменту и просьба к агенту | выполнено | `test_tz_compliance.py::test_expert_comment_proposal_needs_expert_confirmation` | |
| FR-48 | Правка по замечанию эксперта в пределах модуля, после его подтверждения | выполнено | там же; часы и РО не меняются | |
| FR-49 | Приём элемента или модуля; модуль только при всех проверенных | выполнено | `ITEMS_NOT_CHECKED`, `test_access.py::test_module_accept_requires_all_items` | |
| FR-50 | Руководитель: списки за период и страница готовности | выполнено | `test_extras.py::test_head_filter`, `test_access.py::test_head_sees_quality_and_owners` | |
| FR-51 | Индекс готовности 100 % при 10/10 и всех модулях | выполнено | `agent/workflow.py (readiness)`, SPEC-FLOW-20 | |
| FR-52 | Проект приказа и .docx без реквизитов | выполнено | `test_spec_export.py::test_order_draft` | |
| FR-53 | Возврат с обязательным комментарием, уведомление | выполнено | `COMMENT_REQUIRED`, `programs/router.py (approval)` | |
| FR-54 | .docx по шаблону АЦР, реквизиты пустые | выполнено | `test_tz_compliance.py::test_dpp_curriculum_and_utp_headers_follow_template`, `test_tz_compliance.py::test_doop_staff_table_with_blank_names` | |
| FR-55 | Слайды .pptx, планы лекций .docx | выполнено | `test_spec_export.py::test_lectures_docx` | |
| FR-56 | GIFT и Moodle XML | выполнено | `test_spec_export.py::test_gift_and_moodle_xml` | |
| FR-57 | JSON по схеме 4.8 | выполнено | `test_access.py::test_json_export_follows_schema_48` | |
| FR-58 | Журнал: кто, что, когда, версии, решения | выполнено | `GET /events`, `test_spec_service.py::test_events_with_before_after` | |
| FR-59 | Уведомления в интерфейсе и по почте по настройке | выполнено | `test_spec_service.py::test_notify_email_by_profile` | |
| FR-60 | Адаптация с сохранением графа компетенций | выполнено | `test_extras.py::test_adapt_keeps_competencies_and_resolves_hours` | |
| FR-61 | Актуализация по реестру версий | выполнено | `test_extras.py::test_actualize_text_and_program` | |
| FR-62 | Режим auto без вопросов, с допущениями | выполнено | `test_core.py::test_open_cases_auto`, `test_access.py::test_auto_async_returns_202_and_job_result` | |
| FR-63 | Переключатель ролей с числом задач | выполнено | `GET /me/tasks`, `test_extras.py::test_sandbox_and_tasks` | |

## 4.4 Интерфейс: экраны и правила блокировки

Экраны таблицы 10 реализованы в `frontend/src/pages/Program.tsx` (шаги методиста, вычитка, утверждение), `Programs.tsx`, `Reviews.tsx`, `Kb.tsx`, `Admin.tsx`. Сквозной сценарий в браузере проверяет параллельная работа над `e2e/`.

| № | Экран или правило | Статус | Доказательство |
|---|---|---|---|
| Э-01 | Запрос: поле, вложения, сообщения агента, «Распознанные параметры», переключатель базы | выполнено | `Program.tsx`, `Programs.tsx` |
| Э-02 | Вопросы: до 5, «Отвечено n из 5», «На ваше усмотрение» | выполнено | `Program.tsx` |
| Э-03 | Каркас: редактируемые часы, цель, компетенции, ПС | выполнено | `Program.tsx`, `PATCH /skeleton` |
| Э-04 | Проверка: ✓ ! ✕, матрица компетенций, «Утвердить каркас», «Вернуть с комментарием» | выполнено | `Program.tsx` |
| Э-05 | Сборка: прогресс модулей, лента «Что делает агент», токены и стоимость | выполнено | `Program.tsx`, прогресс задания |
| Э-06 | Отчёт: правила, «Для методиста», матрица, выгрузки | выполнено | `Program.tsx` |
| Э-07 | Правка: «Было / Станет», «Что затронет правка» | выполнено | `Program.tsx` |
| Э-08 | Согласование: сводка 10 из 10, эксперты, «Передать агенту», журнал | выполнено | `Program.tsx` |
| Э-09 | Вычитка: «Мои модули», «n из N проверено», «Попросить агента», «Принять модуль» | выполнено | `Program.tsx`, `Reviews.tsx` |
| Э-10 | Утверждение: готовность, «Качество комплекта», «Решения людей», «Заполняется при подписании» | выполнено | `Program.tsx` |
| Б-01 | «Ответить и собрать каркас» только при ответах на все вопросы | выполнено | `Program.tsx` (счётчик) |
| Б-02 | «Перейти к проверке» только при сходящихся часах | выполнено | `Program.tsx` («Сначала исправьте часы») |
| Б-03 | «Утвердить каркас» без ✕ и с решениями по «!» | выполнено | `SKELETON_HAS_ERRORS`, `DECISIONS_PENDING` |
| Б-04 | Генерация только после утверждения | выполнено | `SKELETON_NOT_APPROVED` |
| Б-05 | «Перейти к согласованию» при 10/10 | выполнено | `BLOCKING_FAILED` |
| Б-06 | «Применить правку» при сходящихся часах и не меньше 2 средствах на РО | выполнено | `EDIT_REJECTED`, SPEC-FLOW-15 |
| Б-07 | «Принять модуль» при всех проверенных элементах | выполнено | `ITEMS_NOT_CHECKED` |
| Б-08 | «Отправить на утверждение» при всех принятых модулях и 10/10 | выполнено | `MODULES_NOT_ACCEPTED` |
| Б-09 | «Утвердить и подготовить проект приказа» при готовности 100 % | выполнено | `NOT_READY` |
| Б-10 | «Вернуть с комментарием» только с комментарием | выполнено | `COMMENT_REQUIRED` в трёх местах |

## 4.5 Навыки агента

| № | Требование | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| Н-01 | intake: разбор запроса и файлов, повторы при невалидном JSON | выполнено | `skills/intake`, `test_spec_llm_client.py::test_invalid_json_feedback_then_success` | |
| Н-02 | classify: тип, шаблон, база, кандидаты ПС | выполнено | `skills/classify` (правила без модели) | |
| Н-03 | clarify: до 5 вопросов, значения по умолчанию | выполнено | `skills/clarify` (правила без модели) | |
| Н-04 | skeleton: цель, компетенции, модули, веса | выполнено | `skills/skeleton`, `test_spec_misc.py::test_skeleton_llm_structure_limits` | |
| Н-05 | hours_solver: без модели, до 2 с на 500 ч | выполнено | `solver/hours.py`, синтетический запуск 500 ч | |
| Н-06 | content: 6 видов материалов, 6 потоков | выполнено | `skills/content`, `test_spec_content.py` | |
| Н-07 | validate: 23 правила кодом, судья на 4 | выполнено | `validation/rules.py`, `validation/judge.py` | |
| Н-08 | repair: до 2 попыток на элемент | частично | `validation/repair.py:22` | исправления детерминированные, без модели-судьи из ТЗ (Qwen3 235B) |
| Н-09 | export: .docx, .pptx, GIFT, Moodle XML, JSON без модели | выполнено | `export/service.py` | |
| Н-10 | review_assist: предложение, затрагиваемые элементы, песочница | выполнено | `test_spec_review_assist.py` | |
| Н-11 | workflow: конечный автомат, состояние после каждого шага | частично | `agent/workflow.py`, `programs/service.py (save)` | навыки вызываются прямым импортом, а не по каталогу; новый навык требует правки оркестратора |
| Н-12 | Навык: SKILL.md, schema_in.json, schema_out.json, тесты | частично | 11 каталогов `skills/*` со SKILL.md, schema_in.json и schema_out.json (сверка с моделями — `test_spec_skill_schemas.py`) | тесты лежат в общем каталоге `tests/`, а не внутри каталогов навыков; `schema_in.json` минимальны (`type: object`) |

## 4.6 Алгоритм распределения часов

| № | Шаг алгоритма | Статус | Доказательство |
|---|---|---|---|
| А-01 | Часы модулей методом наибольших остатков с правилом равных остатков | выполнено | `solver/hours.py:22`, `test_spec_solvers.py::test_largest_remainder_tie_break` |
| А-02 | Виды работы: ЛК и СРС по долям, ПР закрывает строку | выполнено | `solver/hours.py (_split_kinds)`, SPEC-SOLVER-05 |
| А-03 | Темы тем же методом, суммы тем равны модулю | выполнено | `test_tz_compliance.py::test_solver_property_all_levels` |
| А-04 | Стажировка: ЛК = ПР = ЛБ = 0 во всех строках | выполнено | там же, кейс 5 (254 + 2 ч) |
| А-05 | Календарь и варианты при превышении срока | выполнено | `solver/calendar.py:34`, кейс 5: три варианта, выбран `six_days` |
| А-06 | Проверка V-01…V-10 до показа каркаса | выполнено | `agent/workflow.py (skeleton_step)` |

## 4.7 Правила автопроверки

Все 27 правил объявлены в `validation/rules.py:486` с номером блокирующей проверки; тест `test_spec_rules.py::test_27_rules_kinds`.

| № | Правило | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| V-01 | Сумма тем равна модулю по видам | выполнено | `rules.py:120`, `test_spec_rules.py::test_v05_v06_v07_hours_rules` | |
| V-02 | ЛК + ПР + ЛБ + СРС = «Всего» в каждой строке | выполнено | `rules.py:131` | |
| V-03 | Сумма модулей равна итоговой строке | выполнено | `rules.py:144` | |
| V-04 | Итог и ИА равны объёму | выполнено | `rules.py:156` | |
| V-05 | Контактная работа в тексте равна плану | выполнено | `rules.py:163`, `test_spec_rules.py::test_v05_v06_v07_hours_rules` | |
| V-06 | Стажировка без аудиторных часов | выполнено | `rules.py:172` | |
| V-07 | Доля практики не ниже заданной (40 % для ДПП ПК) | выполнено | `rules.py:186` | |
| V-08 | Все обязательные разделы шаблона | выполнено | `rules.py:199`, `test_spec_rules.py::test_v08_v09_completeness` | |
| V-09 | Материалы из запроса, темы слайдов совпадают с УТП | выполнено | `rules.py:215` | |
| V-10 | Нагрузка и срок | выполнено | `rules.py:240`, `test_spec_rules.py::test_v10_calendar` | |
| V-11 | Реквизиты, ФИО, подписи пустые | выполнено | `rules.py:263` (проверяет и раздел 3.4), `test_spec_rules.py::test_v11_staff_section` | |
| V-12 | РО раскрыт в теме | выполнено | `rules.py:272`, `test_spec_rules.py::test_v12_v13_coverage` | |
| V-13 | РО проверяется не меньше чем двумя средствами | выполнено | `rules.py:305` | |
| V-14 | Вопрос и задание привязаны к РО | выполнено | `rules.py:314` | |
| V-15 | ПС и ТФ из реестра, в ДООП ПС нет | выполнено | `rules.py:322`, `test_spec_rules.py::test_v15_v16_sources` | |
| V-16 | Источник найден или помечен | выполнено | `rules.py:345` | |
| V-17 | 8-граммы меньше 5 % | выполнено | `rules.py:360` | |
| V-18 | Критерии и баллы у задания | выполнено | `rules.py:380` | |
| V-19 | Ровно один верный ответ | выполнено | `rules.py:385` | |
| V-20 | Правка меняет только потомков | выполнено | `rules.py:391`, `agent/workflow.py (edit)` | |
| V-21 | Пререквизиты тем (судья) | выполнено | `rules.py:407` (эвристика), уточнение судьёй `validation/judge.py` | |
| V-22 | РО проверяем (судья) | выполнено | `rules.py:425`, предложение формулировки | |
| V-23 | Версии библиотек актуальны | выполнено | `rules.py:430`, `registry/tools.json` | |
| V-24 | Примеры кода выполняются | выполнено | `rules.py:444`, `validation/sandbox.py` | |
| V-25 | Нет дублей тем (сходство эмбеддингов bge-m3 > 0,85) | частично | `rules.py:451` | сходство считается по словам, а не по эмбеддингам bge-m3 |
| V-26 | Русский язык, термины поясняются (судья) | выполнено | `rules.py:463` (доля кириллицы), судья | |
| V-27 | Обещания реалистичны, разрыв показан (судья) | выполнено | `rules.py:473`, заметка агента в кейсе 4 | |
| V-* | Калибровка судьи на золотом наборе (Q-24) | частично | `validation/judge.py`, `test_spec_judge.py` | золотого набора из 50 размеченных фрагментов в `testset/` нет |

## 4.8 Модель данных и JSON

Комплект хранится как граф с устойчивыми идентификаторами (`programs/schemas.py`), выгрузка `json` и поле `kit` автопрогона строятся `export/service.py:427` (kit_json). Проверено на ответе кейса 3: у компетенции `code, ps_code, tf_codes, indicators`; у индикатора `kind, outcomes`; у РО `code, verb, bloom_level`; у модуля `hours {total, lk, pr, lb, srs}, expert_id, review_status`; у темы `weight, prerequisites, lo_ids`; у вопроса `options, key, lo_ids, difficulty`; у задания `criteria [{text, points}]`; у лекции `duration_min, plan, code_examples, slides`; у источника `kind, bibl, url, confirmed, checked_at`.

| № | Сущность | Статус | Доказательство |
|---|---|---|---|
| D-01 | OrgProfile | выполнено | `registry/org_profile.json`, `GET/PUT /org/profile` |
| D-02 | Program | выполнено | `ProgramDoc`, поля `type, volume_h, audience, entry_level, form, duration, calendar, final_assessment, status, version` |
| D-03 | Module | выполнено | `Module` |
| D-04 | Topic | выполнено | `Topic` |
| D-05 | Competency | выполнено | `Competency` |
| D-06 | Indicator | выполнено | `Indicator` (`know, can, own`) |
| D-07 | LearningOutcome | выполнено | `LearningOutcome` |
| D-08 | Assessment | выполнено | `Assessment` (`test, seminar, project, interview, final`) |
| D-09 | Question | выполнено | `Question_` |
| D-10 | Task | выполнено | `Task` |
| D-11 | Lecture | выполнено | `Lecture` |
| D-12 | Slide | выполнено | `Slide` |
| D-13 | Source | выполнено | `Source` |
| D-14 | ReviewTask | выполнено | `GET /reviews` (`rid, items_total, items_done, status`) |
| D-15 | Comment | выполнено | `Comment` (`node_id, agent_proposal, status`) |
| D-16 | Approval | выполнено | `Approval` (`stage, actor, decision, comment, at`) |
| D-17 | AuditEvent | выполнено | таблица событий, `GET /events` с `before/after/version` |
| D-18 | Фрагмент JSON 4.8 (program, competencies, modules, questions) | выполнено | `test_access.py::test_json_export_follows_schema_48` |
| D-19 | Хранилище: SQLite для ВМ без Docker и тестов | выполнено | `core/db.py`; PostgreSQL см. 4.11 |

## 4.9 Программный интерфейс

### Методы (таблица 19)

| № | Метод | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| M-01 | POST /programs (interactive, auto) | выполнено | `programs/router.py (create_program)`; для файлов также `POST /programs/upload` | |
| M-02 | GET /programs/{id} | выполнено | `get_program`, поле `program` по схеме 4.8 | |
| M-03 | POST /programs/{id}/answers | выполнено | `answers` (202, job_id) | |
| M-04 | PATCH /programs/{id}/skeleton | выполнено | `patch_skeleton` | |
| M-05 | POST /programs/{id}/skeleton/approve | выполнено | `approve` (approve или return) | |
| M-06 | GET /programs/{id}/report | выполнено | `report` | |
| M-07 | POST /programs/{id}/edits (dry_run) | выполнено | `edits` | |
| M-08 | GET versions, POST versions/{v}/restore | выполнено | `versions`, `restore` | |
| M-09 | PUT /programs/{id}/modules/{m}/expert | выполнено | `assign_expert` | |
| M-10 | GET /reviews | выполнено | `my_reviews` | |
| M-11 | POST /reviews/{rid}/comments | выполнено | `review_comment` | |
| M-12 | POST /reviews/{rid}/decision | выполнено | `review_rid_decision` | |
| M-13 | POST /programs/{id}/submit | выполнено | `submit` | |
| M-14 | POST /programs/{id}/approval | выполнено | `approval` | |
| M-15 | GET /programs/{id}/export/{format} | выполнено | `export_file`; форматы `docx, pptx, gift, moodle_xml, json, order_draft` и дополнительно `lectures_docx` | |
| M-16 | GET /programs/{id}/events | выполнено | `events` | |
| M-17 | GET /jobs/{job_id} | выполнено | `job`, статусы `queued, running, done, failed` | |
| M-18 | PUT /org/profile, POST /org/documents, PUT /org/registry | выполнено | `programs/extra_router.py` | |
| M-19 | GET /health с доступностью моделей | частично | `main.py` (`/health`, `/api/v1/health`) | отдаёт только признак включённой модели; проверка доступности моделей вынесена в `GET /api/v1/llm/status` |
| M-20 | Bearer-токен с ролью, OpenAPI на /docs, длительные операции 202 с job_id | выполнено | `core/security.py`, `test_spec_misc.py::test_cors_and_docs`, `test_access.py::test_auto_async_returns_202_and_job_result` | |

### Ошибки (таблица 20)

Тело ошибки `{"code", "message_ru", "details"}` формирует `core/errors.py:58`; внутренние детали не раскрываются (`test_spec_misc.py::test_unhandled_error_hides_details`).

| № | Код | Статус | Доказательство |
|---|---|---|---|
| E-400 | BAD_REQUEST | выполнено | `core/errors.py:26` |
| E-401 | UNAUTHORIZED | выполнено | `core/errors.py:31` |
| E-403 | FORBIDDEN_ROLE | выполнено | `core/errors.py:36` |
| E-404 | NOT_FOUND | выполнено | `core/errors.py:41`, неизвестный путь `/api/*` тоже JSON (`main.py`) |
| E-409 | SKELETON_NOT_APPROVED и другие коды состояния | выполнено | `core/errors.py:46` и коды в `agent/workflow.py` |
| E-422 | VALIDATION_ERROR | выполнено | `core/errors.py:69` |
| E-429 | RATE_LIMIT | выполнено | `core/errors.py:53`, `test_spec_misc.py::test_parallel_jobs_limit` |
| E-500 | INTERNAL_ERROR | выполнено | `core/errors.py:77` |

### Контракт автопрогона (таблица 21 и правила режима)

| № | Требование | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| C-01 | Один вызов `POST /api/v1/programs?mode=auto`, тело `request, attachments[{name, content_base64}], wait` | выполнено | `programs/router.py (CreateProgram)` | |
| C-02 | Вопросы не задаются, пустые поля из профиля, предложения «!» принимаются | выполнено | `fill_defaults`, `approve_skeleton(auto=True)` | |
| C-03 | Auto-approve при отсутствии ✕ | выполнено | `test_tz_compliance.py::test_auto_calendar_choice_refreshes_skeleton_report` (исправлено в этой сверке: устаревший ✕ по V-10 мешал auto-approve стажировки) | |
| C-04 | После двух попыток repair статус `done_with_errors` и список правил | выполнено | `_auto_pipeline`, `failed_rules` | |
| C-05 | `wait = true`: 200 после сборки, иначе 202 с job_id | выполнено | `test_access.py::test_auto_async_returns_202_and_job_result` | |
| C-06 | Поля `program_id, status, assumptions, skeleton, kit` | выполнено | `programs/router.py (_auto_response)` | |
| C-07 | `report`: 27 правил, n из 10, матрица покрытия | выполнено | `report.rules_passed, rules_total, blocking_checks, coverage` | |
| C-08 | `files`: ссылки на выгрузки | выполнено | `test_spec_export.py::test_auto_run_lists_all_exports` | |
| C-09 | `timing_s` и `tokens` (вход, выход, рубли без НДС) | выполнено | `timing_s.skeleton, kit, total`; `tokens.in, out, cost_rub` | |
| C-10 | Адаптер под формат организаторов без изменения навыков | частично | вход и выход собраны в `_auto_response` | отдельного адаптера нет; формат организаторов не публиковался |

## 4.10 Нефункциональные требования

| № | Требование | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| NFR-01 | Каркас 16…500 ч до 180 с | частично | бюджеты навыков, `timing_s` | нет замера на живой модели (5 кейсов и 10 синтетических по 3 прогона) |
| NFR-02 | Комплект 72 ч до 1 200 с | частично | `timing_s.kit` | то же |
| NFR-03 | Параллелизм генерации не меньше 4, по умолчанию 6 | частично | `gen_workers = 6`, `workers = max(4, …)` | одновременных запросов к шлюзу 2 (`llm_concurrency`) |
| NFR-04 | Программа 500 ч с прогрессом и прогнозом | выполнено | синтетический запуск 500 ч: `done`, 10/10; прогресс `eta_s` в `generate_kit` | |
| NFR-05 | Пересчёт часов до 1 с, переход экранов до 2 с | выполнено | `test_spec_solvers.py::test_recompute_is_fast_and_offline`; переходы в SPA без сервера | |
| NFR-06 | ВМ 2 ядра, 4 ГБ; память не больше 3 ГБ | выполнено | `docker-compose.yml` (`mem_limit: 2g`), `max_parallel_jobs = 4` | |
| NFR-07 | Только Cloud.ru, ключ в окружении | выполнено | `core/config.py`, `.env.example`; ключ не в репозитории | |
| NFR-08 | Повторы до 2 раз, резерв, сохранение после шага, перезапуск | выполнено | `test_spec_llm_client.py::test_server_errors_retry_then_reserve`, `test_spec_misc.py::test_resume_jobs_on_start` | |
| NFR-09 | Детерминизм солвера и проверок, температура каркаса и проверки до 0,3 | выполнено | `test_spec_solvers.py::test_largest_remainder_deterministic`; skeleton 0.2, validate 0.1, судья 0.0 | |
| NFR-10 | Bearer-токены с ролью, ключи не в логах | выполнено | `test_core.py::test_roles`, `test_auth.py::test_settings_secret_masked_encrypted_and_applied` | |
| NFR-11 | ФИО не заполняются, данные обезличены | выполнено | V-11, SPEC-EXPORT-03, SPEC-EXPORT-13 | |
| NFR-12 | Журнал всех действий | выполнено | `programs/service.py:63` (log_event), журнал организации | |
| NFR-13 | Интерфейс, ошибки, комплект на русском | выполнено | `message_ru`, V-26 | |
| NFR-14 | Стоимость 72 ч не больше 150 ₽ | частично | учёт токенов и рублей (`tokens.cost_rub`), дневной бюджет | нет замера на живой модели |
| NFR-15 | Развёртывание одной командой, порт 8000, автоподъём | частично | `docker compose up -d --build`, `restart: unless-stopped`, `scripts/run_vm.sh` | в compose один сервис вместо пяти (nginx, worker, PostgreSQL, Redis не используются) |
| NFR-16 | Новый навык без изменения оркестратора, шаблон через профиль | частично | навыки находит `skills/base.py (load_skills)`, шаблоны в профиле | вызов навыков в оркестраторе прямой; см. Н-11 |

## 4.11 Архитектура, стек, безопасность и разработка

| № | Требование | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| T-01 | SPA на React и TypeScript | выполнено | `frontend/package.json` (React 19, TS 5.8, Vite 6) | |
| T-02 | nginx как единая точка входа | частично | SPA и API отдаёт FastAPI (`main.py`) на порту 8000 | nginx нет (ТЗ допускает это для запуска без Docker) |
| T-03 | API на FastAPI, Pydantic 2 | выполнено | `requirements.txt` | |
| T-04 | Оркестратор как конечный автомат | выполнено | `Status` в `programs/schemas.py`, переходы в `agent/workflow.py` | |
| T-05 | Исполнитель заданий arq и Redis, без Docker встроенная очередь | частично | встроенная очередь asyncio (`programs/service.py:258`), продолжение после перезапуска | arq и Redis не используются |
| T-06 | Слой моделей: SDK openai, повторы, резерв, учёт | выполнено | `llm/client.py`, `test_spec_llm_client.py` | |
| T-07 | База знаний PostgreSQL и pgvector, bge-m3, реранкер | частично | `kb/orgdocs.py` (JSON-хранилище, косинус по эмбеддингам шлюза) | pgvector, bge-m3 и реранкера нет |
| T-08 | Хранилище PostgreSQL 16, SQLAlchemy 2, Alembic | частично | SQLAlchemy 2 и SQLite (`core/db.py`) | PostgreSQL и миграций Alembic нет |
| T-09 | Разбор файлов python-docx, PyMuPDF | выполнено | `kb/files.py` | |
| T-10 | Выгрузка python-docx, python-pptx, lxml | выполнено | `export/service.py` | |
| T-11 | Песочница: процесс с rlimit, Landlock, seccomp; без сети, 10 с, 512 МБ | частично | `validation/sandbox.py:19` (rlimit CPU, память, процессы), запрет системных модулей, `test_spec_sandbox.py::test_network_is_blocked`; контейнер только для чтения | Landlock и seccomp не применяются |
| T-12 | Почта SMTP по настройке профиля | выполнено | `programs/service.py:106`, `test_spec_service.py::test_send_mail_smtp` | |
| T-13 | Правила слоя моделей: паузы 1 и 3 с, резерв, 429 снижает параллельность | выполнено | `llm/client.py`, `test_spec_llm_client.py::test_overload_429_backoff` | |
| T-14 | Провайдер fixtures для тестов и CI | выполнено | `LLM_PROVIDERS=fixtures` | |
| T-15 | Переменные окружения таблицы 26 | выполнено | `core/config.py`: добавлены `SANDBOX_TIMEOUT_S` (10) и `SANDBOX_MEMORY_MB` (512), их читает `validation/sandbox.py`; `LLM_MODEL_RERANK` и `REDIS_URL` читаются, но помечены в `docs/configuration.md` как зарезервированные (реранкера и Redis нет — см. T-05, T-07); `LLM_CONCURRENCY` по умолчанию 2 из-за ограничения шлюза хакатона, меняется переменной; `test_spec_tokens.py::test_env_settings_table_26`, `test_spec_sandbox.py::test_limits_from_settings` | |
| T-16 | Пароли bcrypt | выполнено | `test_spec_misc.py::test_passwords_bcrypt_only` | |
| T-17 | JWT 30 мин и токен обновления 30 дней | выполнено | `core/security.py (create_token, decode_token)`: токен доступа 30 мин (`typ=access`), токен обновления 30 дней (`typ=refresh`), `POST /auth/refresh`; токены не взаимозаменяемы; интерфейс при 401 один раз обновляет сессию (`frontend/src/api.ts`, vitest); `test_spec_tokens.py::test_access_30_min_and_refresh_30_days`, `test_spec_tokens.py::test_refresh_endpoint_and_token_types` | |
| T-18 | Лимиты: вход 5 в минуту с адреса, создание программ 30 в час, api по профилю | выполнено | вход: `auth/router.py (login)`, `test_tz_compliance.py::test_login_failures_rate_limited`; создание программ: `core/security.py (check_program_rate)` — `programs_per_hour` 30 в час на пользователя, для роли `api` — `api_programs_per_hour` (оба в настройках профиля «Лимиты»), 429 с `message_ru`, `test_spec_tokens.py::test_program_creation_limit_per_user`; анонимный автопрогон 12 в час с адреса; 4 параллельных задания | |
| T-19 | Загрузка файлов: сигнатура, 20 МБ, распаковка до 100 МБ, макросы не исполняются, PDF ограничен | выполнено | `kb/files.py:29` и `_parse_docx`; PDF до 200 страниц | |
| T-20 | Секреты только в окружении, ключ и тексты запросов не в журнале | выполнено | `.env.example`, `llm/client.py` (лог без текста запроса), шифрование секретов настроек | |
| T-21 | Спецификации EARS и ADR | частично | `specs/*.md` в EARS, трассировка `scripts/spec_trace.py` | каталога ADR (`docs/decisions/`) нет |
| T-22 | ruff, mypy strict, pytest с покрытием не ниже 70 %, hypothesis для солвера | частично | ruff чист, покрытие 90 %, `test_tz_compliance.py::test_solver_property_all_levels` | mypy не настроен; порог в `.coveragerc` 60 %, а не 70 % (фактически 90 %) |
| T-23 | Фронтенд: ESLint, сборка TS, vitest | выполнено | `frontend/eslint.config.js` (правила TS и хуков React, 0 предупреждений), `frontend/src/__tests__/api.test.ts` (vitest, jsdom), `npm run check` = lint + test + build | |
| T-24 | autorun.py со сверкой чек-листов, отчётом времени и токенов | выполнено | `scripts/autorun.py` | |
| T-25 | smoke.py, e2e (Playwright), export_openapi.py --check | выполнено | `scripts/smoke.sh` (основной сценарий и выгрузки), `scripts/e2e_regression.py` (API по всем ролям и 5 кейсам, 1381 проверка), `e2e/ui_roles.spec.cjs` (Playwright, 90 проверок по ролям), `scripts/export_openapi.py --check`, `test_reproducibility.py::test_openapi_schema_matches_code` | smoke написан на bash, а не Python |
| T-26 | CI на каждый push или `make check` | выполнено | `.gitea/workflows/ci.yml` (ruff, pytest с порогом покрытия, трассировка SDD, OpenAPI, ESLint, vitest, сборка), `Makefile` (`make check`, `make e2e`) | |

Запись ADR учтена в T-21. Статус «не выполнено» в разделе 4.11 у трёх строк: T-23 (ESLint и vitest), T-25 (smoke, e2e, `export_openapi`) и T-26 (CI).

## 5 Метрики качества

| № | Метрика | Статус | Как измеряется в коде | Что не так |
|---|---|---|---|---|
| Q-01* | Арифметика часов | выполнено | V-01…V-07, каждый прогон | |
| Q-02* | Полнота шаблона | выполнено | V-08 | |
| Q-03* | Календарная выполнимость | выполнено | V-10 | |
| Q-04* | Поля для людей | выполнено | V-11 | |
| Q-05* | Покрытие компетенций | выполнено | V-12, V-13, матрица покрытия | |
| Q-06* | Привязка оценивания к РО | выполнено | V-14 | |
| Q-07 | Уровень заданий по Блуму | частично | `bloom_level` у РО | доля заданий «применять и выше» не считается |
| Q-08 | Дубли тем между модулями | частично | V-25 по словам | не по эмбеддингам bge-m3 |
| Q-09* | Источники | выполнено | V-15, V-16, `unconfirmed_sources` | |
| Q-10 | Актуальность ИТ-источников | частично | V-23 по реестру версий | доля изданий не старше 5 лет не считается |
| Q-11 | Исполнимость кода | выполнено | V-24, `GET /sandbox`, блок «Качество комплекта» | |
| Q-12* | Оригинальность | выполнено | V-17 | |
| Q-13 | Корректность ключей (эксперт) | частично | V-19 кодом, приём элементов экспертом | доля, подтверждённая экспертом, не считается |
| Q-14 | Правдоподобие дистракторов | не выполнено | | оценки эксперта и ответов слушателей в системе нет (метрика пилота) |
| Q-15* | Измеримость заданий | выполнено | V-18 | |
| Q-16 | Психометрия теста | не выполнено | | ответов слушателей нет (метрика пилота) |
| Q-17 | Доля правок | выполнено | `agent/workflow.py (quality)`: доля правок людей | |
| Q-18 | Принято без правок | выполнено | `quality.accepted_without_edits` | |
| Q-19 | Экспертная оценка 1…5 | частично | оценка при приёме модуля (`score`), среднее в `quality` | одна оценка вместо рубрики из пяти критериев |
| Q-20 | Согласие экспертов (каппа Коэна) | не выполнено | | двойной вычитки нет (метрика пилота) |
| Q-21 | Возвраты на утверждении | выполнено | `approvals` со стадией `program` и решением `return`, журнал | |
| Q-22 | Срок до утверждения | частично | даты в журнале и `approvals` | рабочие дни от запроса до утверждения не вычисляются |
| Q-23 | Время людей | частично | блок `effect` (оценка по нормам) | таймеров работы методиста и эксперта нет |
| Q-24 | Калибровка судьи | не выполнено | | золотого набора нет |
| Q-25* | Точечная правка без регрессий | выполнено | V-20, `EDIT_REJECTED` | |
| Q-26 | Пункты чек-листов | частично | `scripts/autorun.py (_checks)`: 47 проверок кодом | на fixtures 44 из 51 пункта (раздел ниже); на живой модели не прогонялось |

## 6.4 Критерии приёмки

| № | Критерий | Статус | Доказательство | Что не так |
|---|---|---|---|---|
| ПР-01 | Время каркаса до 180 с во всех прогонах | частично | `timing_s` | нет живых прогонов |
| ПР-02 | Время комплекта 72 ч до 1 200 с | частично | `timing_s` | нет живых прогонов |
| ПР-03 | Блокирующие проверки 10 из 10 в каждом комплекте | выполнено | все 5 кейсов и 3 синтетических запроса: 10/10 | |
| ПР-04 | Пункты чек-листов не меньше 90 % (46 из 51) | частично | 44 из 51 на fixtures (86 %) | недобор из-за типовой структуры без модели и раздельных часов очной и дистанционной работы |
| ПР-05 | Ответы эндпоинта по контракту 100 % | выполнено | `test_core.py::test_open_cases_auto`, раздел C | |
| ПР-06 | Источников без подтверждения и без пометки 0 | выполнено | `unconfirmed_sources` и пометки, V-16 | |
| ПР-07 | Время методиста в сценарии кейса 3 до 6 ч | не выполнено | | замер с методистом не проводился |
| ПР-08 | Доля правок до 30 % | не выполнено | | замер на живом комплекте не проводился |

## Чек-листы открытых тест-кейсов

Прогон на fixtures (детерминированные ответы навыков без модели). Пункты, которые зависят от смысла текста, на fixtures закрываются типовой структурой направления; с моделью они должны закрываться содержанием, но живой прогон не выполнялся.

### Общие требования

| № | Пункт | Статус | Доказательство |
|---|---|---|---|
| О-1 | Часы сходятся на всех уровнях, итог с ИА равен объёму | выполнено | 16, 36, 72, 72, 256 ч; V-01…V-04 |
| О-2 | Все обязательные разделы заполнены по образцам | выполнено | V-08, сверка DOCX ниже |
| О-3 | Каждый РО в теме и не меньше двух средств | выполнено | V-12, V-13 |
| О-4 | Источники, акты, ПС существуют, неподтверждённые помечены | выполнено | V-15, V-16, `unconfirmed_sources = 0` |
| О-5 | Реквизиты, ФИО, подписи пустые | выполнено | V-11, титул «Приказом № ____-ОБР от «___» __________ 20__ г.» |
| О-6 | .docx и JSON, всё на русском | выполнено | выгрузки всех форматов, код 200 |

### Запрос 1. «Первые шаги в Python» (ДООП, 16 ч)

| № | Пункт | Статус | Доказательство или причина |
|---|---|---|---|
| 1.1 | Шаблон общеразвивающей программы | выполнено | `type = doop` |
| 1.2 | 16 ч, практики не меньше 8 ч | выполнено | ПР 9 ч, ИА 2 ч |
| 1.3 | 8 занятий по 2 ч за 4 недели | выполнено | `sessions = 8`, `weeks = 4` |
| 1.4 | Сложные темы не раньше переменных, условий, циклов | выполнено | модули «Знакомство», «Условия и циклы», «Списки и функции», «Проект»; V-21 pass |
| 1.5 | Защита проекта с понятными подростку критериями | выполнено | Приложение № 1, критерии с баллами |
| 1.6 | Тест 10 вопросов с ключами и РО | выполнено | 10 вопросов `test-final` с `lo_ids` |
| 1.7 | Слайды для занятий 1 и 2 по темам УП | выполнено | слайды у тем 1.1 и 1.2 (первые два занятия по 2 ч) |
| 1.8 | Язык понятен школьнику, термины поясняются | частично | V-26 без судьи проверяет только долю кириллицы; пояснение терминов проверяет судья, на fixtures он выключен |
| 1.9 | Нет привязки к ПС | выполнено | `ps_code = null`, у компетенций нет ТФ |

### Запрос 2. «ИИ в работе учителя» (ДПП ПК, 36 ч)

| № | Пункт | Статус | Доказательство или причина |
|---|---|---|---|
| 2.1 | Шаблон ПК, удостоверение | выполнено | `issued_document = Удостоверение о повышении квалификации` |
| 2.2 | 36 ч, часы очной и дистанционной работы разделены явно | частично | 36 ч сходятся; в разделе 1.7 только «с применением ЭО и ДОТ», раздельных часов очной и дистанционной работы нет |
| 2.3 | Связь с ПС «Педагог», коды ТФ верны | выполнено | 01.001, ТФ A/01.6, A/02.6, A/03.6 из реестра |
| 2.4 | Отдельная тема о рисках, этике и персональных данных | выполнено | модуль 5 «Риски, этика и защита персональных данных» |
| 2.5 | Только сервисы, доступные в России | выполнено | `test_extras.py::test_blocked_services_scrubbed`, `test_spec_content.py::test_blocked_services_removed_from_llm_content` |
| 2.6 | Задания на реальных задачах учителя | выполнено | задания по технологической карте урока, дифференциации, проверочным работам |
| 2.7 | Зачёт по портфолио из трёх материалов с требованиями и критериями | выполнено | ИА «Зачёт по портфолио»: план урока, задания, проверочная работа; критерии с баллами |
| 2.8 | Программирование не требуется, входные требования это учитывают | частично | раздел 1.6 типовой («СПО и (или) ВО»), отдельной оговорки об отсутствии навыков программирования нет |

### Запрос 3. «Анализ данных на Python» (ДПП ПК, 72 ч)

| № | Пункт | Статус | Доказательство или причина |
|---|---|---|---|
| 3.1 | 72 ч, график на 4 недели | выполнено | `weeks = 4` |
| 3.2 | pandas, визуализация, SQL, статистика отдельными модулями | выполнено | модули 2…5 |
| 3.3 | Вводный блок по Python первым | выполнено | модуль 1 «Python для пользователей Excel» |
| 3.4 | Структура как в приложенной программе, без копирования текста | выполнено | заметка «беру структуру разделов, текст не переношу»; V-17 pass |
| 3.5 | ПС в области данных с верным кодом | выполнено | 06.042 «Специалист по большим данным» |
| 3.6 | Инструменты и версии актуальны на 2026 год | выполнено | V-23 pass, `registry/tools.json` |
| 3.7 | Итоговый проект: требования к данным, результат, критерии, обезличенные данные | выполнено | 2.5.1 и Приложение 2: данные обезличены, критерии с баллами |
| 3.8 | Задания на банковских ситуациях | частично | на fixtures задания типовые по темам («Выполните практическую работу по теме…»); банковский контекст даёт только модель |
| 3.9 | Слайды для всех лекций модуля pandas | выполнено | слайды у тем 2.1…2.4 |

### Запрос 4. Кибербезопасность для колледжа (неполный)

| № | Пункт | Статус | Доказательство или причина |
|---|---|---|---|
| 4.1 | Сначала вопросы, сборка не начинается | выполнено | в интерактивном режиме статус `questions`; в auto вопросы в `questions_skipped` |
| 4.2 | Вопросы о типе и объёме | выполнено | `program_type`, `volume_h` |
| 4.3 | Вопросы о входном уровне, форме обучения, форме ИА | выполнено | `audience`, `form`, `final_assessment_form` |
| 4.4 | Не больше пяти вопросов, понятных методисту | выполнено | ровно 5, без жаргона |
| 4.5 | После ответов шаблон ПК и ровно 72 ч | выполнено | `type = dpp_pk`, 72 ч |
| 4.6 | Учтено, что студенты получают СПО параллельно | выполнено | раздел 1.6: «лица, получающие среднее профессиональное … образование» |
| 4.7 | ПС в области ИБ с верным кодом | выполнено | 06.033, ТФ A/01.5, B/04.6 |
| 4.8 | Результаты реалистичны для 72 ч, начальный уровень | частично | на fixtures модули типовые («Введение в направление», «Основы направления»); формулировки начального уровня даёт модель |
| 4.9 | Разница ожиданий заказчика и результата показана в отчёте | выполнено | заметка агента «Ожидание заказчика: … начального уровня» |
| 4.10 | Экзамен с практическим заданием, пример и критерии | выполнено | пример задания на стенде и 4 критерия с баллами |

### Запрос 5. Стажировка «DevOps-инженер» (256 ч)

| № | Пункт | Статус | Доказательство или причина |
|---|---|---|---|
| 5.1 | 256 ч: 254 ч СРС и 2 ч ИА | выполнено | totals `srs = 254`, `ia = 2` |
| 5.2 | ЛК, ПР, ЛБ равны нулю во всех строках, включая итог | выполнено | V-06; в итоговой строке УП нули |
| 5.3 | Ошибка образца не перенесена, агент сообщает о ней | выполнено | заметка «таблицы часов не сходятся (12 расх.)» |
| 5.4 | Около двух месяцев, не больше 4 ч в день | частично | 4 ч в день соблюдены; 256 ч при 4 ч в день требуют 64 рабочих дня, агент показал конфликт и выбрал шестидневную неделю (около 11 недель); в двух месяцах уложиться невозможно |
| 5.5 | Темы: Linux, сети, контейнеры, CI/CD, мониторинг, IaC | выполнено | модули 1…6 |
| 5.6 | Текущий контроль собеседованием, вопросы по каждому разделу | выполнено | Приложение 1 «Примерные вопросы для собеседования» (19 вопросов по разделам) |
| 5.7 | Требования к отчёту и критерии защиты | выполнено | Приложение 2 и 2.5.1 |
| 5.8 | ПС системного администрирования с верным кодом | выполнено | 06.026, ТФ из реестра |
| 5.9 | Согласованность при большом объёме, без повторов тем | выполнено | V-12, V-13, V-25 pass |

Итого по чек-листам: 45 выполнено, 6 частично. Пункты 1.8, 2.8, 3.8, 4.8 зависят от модели; пункт 5.4 противоречив в самом запросе (агент показал конфликт); пункт 2.2 требует доработки (см. «Оставшиеся разрывы»).

## Сверка DOCX с шаблонами АЦР

Сгенерированы DOCX для кейса 3 (ДПП ПК, 72 ч), кейса 5 (стажировка, 256 ч) и кейса 1 (ДООП, 16 ч) и сопоставлены с образцами по заголовкам, порядку разделов и шапкам таблиц.

### ДПП ПК (образец: стажировка «Бизнес и системный анализ», 248 ч)

| Раздел образца | В выгрузке | Статус |
|---|---|---|
| Титул: организация, реквизиты, «УТВЕРЖДЕНО Приказом № … от …», вид программы, название, город и год | то же; номер и дата приказа пустые; для стажировки «… В ФОРМЕ СТАЖИРОВКИ» | совпадает |
| 1. Общая характеристика, 1.1 Аннотация, 1.2 Цель | то же | совпадает |
| 1.3 Планируемые результаты: таблица «Виды деятельности · Профессиональные компетенции · Практический опыт · Умения · Знания» | та же таблица | совпадает |
| 1.4 Программа разработана на основе, 1.5 Перечень компетенций, 1.6 Требования к слушателям, 1.7 Форма обучения, 1.8 Объём, 1.9 Выдаваемый документ | то же, в том же порядке | совпадает |
| 2.1 Учебный план: «№ п/п · Наименование разделов программы · Трудоёмкость, всего (час.) · ЛК · ПР · ЛБ · СРС (час.) · Форма аттестации» | та же шапка; итоговая строка пересчитана (в образце она не сходится) | совпадает |
| 2.2 УТП: «Наименование разделов, тем программы … Форма контроля» | до сверки шапка повторяла учебный план; исправлено, `test_tz_compliance.py::test_dpp_curriculum_and_utp_headers_follow_template` | исправлено |
| 2.3 Календарный учебный график | таблица по неделям с ЛК, ПР, ЛБ, СРС, ИА (в образце текст) | расширено |
| 2.4 Рабочая программа: «Наименование компонентов · Содержание · Всего (час.)» | та же таблица | совпадает |
| 2.5 Оценка качества, 2.5.1 Формы аттестации, 2.5.2 Оценочные материалы, 2.5.3 Анализ удовлетворённости | то же | совпадает |
| 3.1 Материально-техническое, 3.2 Учебно-методическое (3.2.1 НПА, 3.2.2 основная, 3.2.3 дополнительная литература, 3.2.4 интернет-ресурсы, 3.2.5 ПО), 3.3 Организация процесса, 3.4 Кадровое обеспечение | то же, в том же порядке | совпадает |
| Приложение 1: вопросы текущего контроля (собеседование) | вопросы собеседования для стажировки, тесты и задания по разделам с ключами | совпадает, расширено |
| Приложение 2: методические указания к итоговой аттестации | требования к работе, критерии с баллами, процедура | совпадает |

### ДООП (образец: «Интенсив по созданию продуктов на основе ИИ», 24 ч)

| Раздел образца | В выгрузке | Статус |
|---|---|---|
| Титул ДООП | «ДОПОЛНИТЕЛЬНАЯ ОБЩЕОБРАЗОВАТЕЛЬНАЯ ОБЩЕРАЗВИВАЮЩАЯ ПРОГРАММА», реквизиты пустые | совпадает |
| Пояснительная записка (без номера) | «1. Пояснительная записка» | совпадает по составу (добавлен номер группы) |
| 1.1 Актуальность, 1.2 Категории обучающихся, 1.3 Цель и задачи, 1.4 Сроки реализации, 1.5 Планируемые результаты, 1.6 Календарный учебный график | то же, в том же порядке | совпадает |
| 2.1 Учебный план: «№ п/п · Наименование разделов/дисциплин/модулей · Общая трудоемкость · Всего аудиторных часов · в т.ч. · Самостоятельная работа · Форма промежуточной аттестации/контроля» | та же структура, подстолбцы «Лекции/теория» и «Практические занятия» развёрнуты | совпадает |
| 2.2 УТП: «Виды учебных занятий · Содержание» | «Тема · Виды учебных занятий · Содержание · Часы» | совпадает, расширено |
| 2.3 Оценочные материалы: «Этап · Артефакт · Кто и как оценивает» | та же таблица | совпадает |
| 2.4 Методические материалы | то же | совпадает |
| 3.1, 3.2, 3.3 Литература (3.3.1, 3.3.2, 3.3.3) | то же | совпадает |
| 3.4 Кадровое обеспечение: таблица «№ · Модуль/Дисциплина в соответствии с УП · ФИО преподавателя · Уч. степень/Звание · Должность» | до сверки только строка-заглушка; добавлена таблица по модулям с пустыми ФИО, `test_tz_compliance.py::test_doop_staff_table_with_blank_names` | исправлено |
| Приложение № 1 «Перечень кейсов компаний-партнёров» | Приложение № 1 «Оценочные материалы» (тесты, задания) | отличается сознательно: перечень кейсов специфичен для интенсива-хакатона |

## Исправлено в этой сверке

| № | Разрыв | Исправление | Тест и требование |
|---|---|---|---|
| 1 | В режиме auto после выбора варианта графика проверки каркаса не пересчитывались: устаревший ✕ по V-10 срывал auto-approve, каркас стажировки утверждался в обход с ложной заметкой «Каркас содержит ошибки ✕» и без записи в `approvals` | `programs/router.py:191` (`_auto_pipeline`): после `choose_calendar_option` пересчёт `build_report(doc, 'skeleton')` | `test_tz_compliance.py::test_auto_calendar_choice_refreshes_skeleton_report`, SPEC-FLOW-35 |
| 2 | Шапка УТП ДПП ПК повторяла учебный план | `export/service.py:91` (`_curriculum`): «Наименование разделов, тем программы» и «Форма контроля» в УТП | `test_tz_compliance.py::test_dpp_curriculum_and_utp_headers_follow_template`, SPEC-EXPORT-12 |
| 3 | В ДООП раздел 3.4 без таблицы образца | `export/service.py:207` (`_doop_staff`) и вызов в `render_docx` (строка 283) | `test_tz_compliance.py::test_doop_staff_table_with_blank_names`, SPEC-EXPORT-13 |
| 4 | V-11 не смотрел раздел «Кадровое обеспечение», где модель могла вписать ФИО | `validation/rules.py:268` (`v11`): добавлен ключ `conditions_org` | `test_spec_rules.py::test_v11_staff_section`, SPEC-RULES-09 |
| 5 | Нет лимита попыток входа (ТЗ 4.11) | `auth/router.py:57-68` (`login`): не больше `login_failures_per_minute` (5) неудачных попыток в минуту с адреса, далее 429; настройка в `core/config.py` | `test_tz_compliance.py::test_login_failures_rate_limited`, SPEC-AUTH-24 |
| 6 | Эксперт не получал уведомление, когда принятый модуль менялся и возвращался на вычитку (US-15) | `programs/router.py:514-529` (`edits`): уведомление назначенному эксперту | `test_tz_compliance.py::test_changed_accepted_module_returns_to_review_and_notifies_expert`, SPEC-FLOW-37 |
| 7 | Нет API-теста цепочки «замечание эксперта, предложение агента, подтверждение экспертом» (FR-41, FR-47, FR-48) | поведение верное, добавлен тест | `test_tz_compliance.py::test_expert_comment_proposal_needs_expert_confirmation`, SPEC-FLOW-36 |
| 8 | Нет property-теста солвера на всех уровнях для 16…500 ч (ТЗ 4.11) | добавлен тест hypothesis: суммы, детерминизм, нули стажировки | `test_tz_compliance.py::test_solver_property_all_levels`, SPEC-SOLVER-04…07 |
| 9 | Токен 12 ч без токена обновления (T-17) | `core/security.py`: токен доступа 30 мин (`typ=access`) и токен обновления 30 дней (`typ=refresh`), `POST /auth/refresh`; старые клиенты с одним `access_token` работают; интерфейс при 401 один раз обменивает токен обновления (`frontend/src/api.ts`) | `test_spec_tokens.py`, SPEC-AUTH-25, SPEC-AUTH-26, SPEC-UI-08 |
| 10 | Нет выдачи и отзыва токенов API (Р-04, US-22) | `auth/tokens.py`, таблица `api_tokens` (только SHA-256), `/admin/api-tokens` (POST, GET, DELETE), вкладка «Токены API» | `test_spec_tokens.py`, SPEC-AUTH-27, SPEC-AUTH-28, SPEC-UI-21 |
| 11 | Нет лимита 30 программ в час на пользователя и лимита роли api (T-18) | `core/security.py (check_program_rate)` в `POST /programs`, `/programs/upload`, `/adapt`; настройки `programs_per_hour`, `api_programs_per_hour` | `test_spec_tokens.py::test_program_creation_limit_per_user`, SPEC-AUTH-29 |
| 12 | Нет `SANDBOX_TIMEOUT_S`, `SANDBOX_MEMORY_MB`, `LLM_MODEL_RERANK`, `REDIS_URL` (T-15) | `core/config.py`, песочница читает лимиты из настроек; реранкер и Redis помечены как зарезервированные | `test_spec_tokens.py::test_env_settings_table_26`, SPEC-API-29, SPEC-SANDBOX-11 |
| 13 | В каталогах навыков нет `schema_out.json`, на который ссылаются SKILL.md (К-17) | `skills/outputs.py`, `scripts/export_skill_schemas.py --check`, 11 файлов `schema_out.json` | `test_spec_skill_schemas.py`, SPEC-SKILLS-16 |

## Оставшиеся разрывы

Крупные разрывы не исправлялись частично, чтобы не оставлять полуготовых реализаций.

1. **Живой прогон на моделях Cloud.ru** (FR-19, FR-31, NFR-01, NFR-02, NFR-14, Q-26, ПР-01, ПР-02, ПР-04): нужен прогон `scripts/autorun.py --url` на стенде с ключом, 5 кейсов и 10 синтетических запросов по 3 раза, с сохранением логов времени и токенов и протоколом испытаний.
2. **Раздельные часы очной и дистанционной работы** (чек-лист 2.2): нужно правило распределения часов по формам (например, ЛК и СРС дистанционно, ПР очно) в солвере, разделе 1.8 и учебном плане. Это изменение модели данных и солвера, а не правка текста.
3. **Инфраструктура стека 4.11**: PostgreSQL с pgvector и Alembic, Redis и arq, nginx, bge-m3 и реранкер, песочница с Landlock и seccomp. Текущая реализация (SQLite, встроенная очередь, FastAPI отдаёт SPA, эмбеддинги шлюза, rlimit и контейнер только для чтения) соответствует варианту ТЗ «без Docker» и ограничениям шлюза хакатона.
4. ~~**Токены**~~: закрыто — JWT 30 минут с токеном обновления на 30 дней (T-17), выдача и отзыв токенов API администратором (Р-04, US-22), лимит 30 программ в час на пользователя и лимит роли `api` в профиле (T-18).
5. **Навыки как переносимые единицы** (Н-11, Н-12, NFR-16): `schema_out.json` добавлены и сверяются с моделями (К-17 закрыт); остались тесты внутри каталога навыка и вызов навыков оркестратором по каталогу, а не прямым импортом.
6. **Инструменты разработки**: mypy strict для solver, validation, export; ESLint и vitest; `scripts/smoke.py`, `scripts/export_openapi.py --check` и `docs/openapi.json`; CI или `make check`; каталог ADR `docs/decisions/`; порог покрытия 70 % в `.coveragerc`.
7. **Метрики пилота** (Q-07, Q-10, Q-13, Q-14, Q-16, Q-19, Q-20, Q-22, Q-23, Q-24): требуют данных экспертов и слушателей, таймеров и золотого набора для калибровки судьи.
8. **Материалы сдачи** (П-03): ТЗ, макеты, `МетодАгент_расчёты.xlsx` и протокол испытаний в репозиторий не положены.
9. **`GET /health`** (M-19): краткий итог доступности моделей (сейчас только признак включённой модели; полная проверка в `GET /api/v1/llm/status`).
10. **Приказ № 499** (FR-07, К-22): сознательно заменён действующим приказом № 266; при приёмке стоит сослаться на утрату силы № 499 с 01.09.2025.
