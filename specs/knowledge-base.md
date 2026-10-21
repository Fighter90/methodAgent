# Нормативная база и база знаний

Префикс требований: `SPEC-KB`. Код: `src/app/kb/registry.py`, `src/app/kb/norms.py`, `src/app/kb/orgdocs.py`, `src/app/kb/files.py`; методы `/kb/*` и `/org/*` в `src/app/programs/extra_router.py`. Подробности — [docs/knowledge-base.md](../docs/knowledge-base.md).

## Назначение

Три слоя знаний: реестры `registry/*.json` (НПА, ПС, ФГОС, литература, версии инструментов, профиль организации) — единственный источник кодов и реквизитов; выжимки актов `registry/norms/*.md` с детерминированным поиском; документы организации, которые загружает администратор. Модуль также разбирает приложенные файлы (PDF, DOCX, текст) и сверяет в них таблицы часов.

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-KB-01 | THE SYSTEM SHALL сливать основные реестры с дополнениями `kb_*.json` по ключу (`code` для ПС и ФГОС, иначе `id`) и исключать из результата записи, утратившие силу. | FR-10 | `test_norms.py::test_repealed_acts_are_not_used` |
| SPEC-KB-02 | THE SYSTEM SHALL не использовать утратившие силу акты (например, приказы № 499 и № 816) ни в реестре, ни в нормативной базе программ. | FR-07, FR-10 | `test_norms.py::test_repealed_acts_are_not_used` |
| SPEC-KB-03 | WHEN подбирается нормативная база ДПП, THE SYSTEM SHALL ставить первыми обязательные акты типа (273-ФЗ, приказ № 266), а остальные добавлять только по ключевым словам запроса (очно-заочная форма сама по себе не означает ДОТ). | FR-07 | `test_norms.py::test_core_and_keyword_acts` |
| SPEC-KB-04 | WHEN подбирается нормативная база ДООП, THE SYSTEM SHALL включать 273-ФЗ, приказ № 629 и санитарные нормы и не включать приказ № 266. | FR-07 | `test_norms.py::test_core_and_keyword_acts` |
| SPEC-KB-05 | WHEN подбирается ПС, THE SYSTEM SHALL выбирать его по ключевым словам реестра (кейсы 2–5 → 01.001, 06.042, 06.033, 06.026) и оставлять в программе не больше 12 ТФ, ближайших к запросу. | FR-07, FR-14 | `test_norms.py::test_profstandards_for_cases` |
| SPEC-KB-06 | WHEN подбирается нормативная база основной программы уровня `school`, `spo` или `vo`, THE SYSTEM SHALL включать 273-ФЗ, обязательные акты уровня и цитируемые по ключевым словам; IF уровень неизвестен, THEN THE SYSTEM SHALL отказать (`ValueError`). | код | `test_norms.py::test_norm_base_for_school_college_university` |
| SPEC-KB-07 | THE SYSTEM SHALL хранить не меньше 52 выжимок актов, ссылаться из них только на существующие записи реестра НПА и искать по ним детерминированно с фильтром по типу программы. | FR-08, FR-10 | `test_norms.py::test_norm_digests_link_to_registry`, `test_norms.py::test_norm_base_for_school_college_university` |
| SPEC-KB-08 | WHEN подбирается литература для школьной программы, THE SYSTEM SHALL брать только документацию и детские источники; WHEN сверяется источник, THE SYSTEM SHALL находить его в реестре по названию или домену. | FR-29 | `test_extras.py::test_sources_school_and_generic_docs` |
| SPEC-KB-09 | WHEN документ организации загружается, THE SYSTEM SHALL принимать его только от администратора (иначе 403), индексировать фрагменты и сохранять карточку в индексе `data_dir/kb`. | FR-09 | `test_extras.py::test_kb_upload_and_search` |
| SPEC-KB-10 | WHEN выполняется поиск по базе знаний, THE SYSTEM SHALL объединять фрагменты документов организации (эмбеддинги или доля общих слов, с бонусом 0,25) и выжимок НПА, отбрасывать оценки не выше 0,05 и сортировать по убыванию оценки. | FR-09 | `test_extras.py::test_kb_upload_and_search` |
| SPEC-KB-11 | THE SYSTEM SHALL определять формат файла по сигнатуре (PDF, DOCX, текст — первые 2000 байт декодируются как UTF-8, даже если разрез приходится на середину буквы); IF формат не распознан, THEN THE SYSTEM SHALL отклонить файл. | FR-02 | `test_extras.py::test_cyrillic_txt_cut_at_2000_bytes_is_text` |
| SPEC-KB-12 | WHEN в приложенном PDF или DOCX есть таблица часов, THE SYSTEM SHALL пересчитать суммы по видам, темам и итоговой строке и показать расхождения методисту, не перенося их в каркас. | FR-05 | `test_skeleton.py::test_pdf_reference_hours_checked` |
| SPEC-KB-13 | IF DOCX после распаковки больше 100 МБ, THEN THE SYSTEM SHALL отклонить файл (защита от zip-бомб). | FR-02 | `test_extras.py::test_kb_docx_zip_bomb_rejected_and_normal_ok` |
| SPEC-KB-14 | WHEN администратор меняет профиль организации, THE SYSTEM SHALL принять только допустимые поля (иначе 400, пароль SMTP — 400) и сразу применять `defaults` к ответам «на ваше усмотрение»; IF профиль меняет не администратор, THEN THE SYSTEM SHALL ответить 403. | FR-13 | `test_access.py::test_admin_profile_registry_and_expert_suggestions` |
| SPEC-KB-15 | WHEN администратор заменяет раздел реестра, THE SYSTEM SHALL записать его поверх образа в `data_dir/registry`, проставить `checked_at` записям без даты и сбросить кэш. | FR-10 | `test_access.py::test_admin_profile_registry_and_expert_suggestions` |
| SPEC-KB-16 | WHEN запрос на ДПП ПК называет аудиторию слушателей (маркетологи, бухгалтеры, HR, экономисты, дизайнеры, журналисты, госслужащие, врачи, медсёстры и др.) или ИТ-направление (frontend, QA, UX/UI, БД, сети, data engineering, проекты, техписатели), THE SYSTEM SHALL выбрать ПС этой профессии из реестра с подтверждёнными кодами ТФ, не меняя ПС открытых кейсов 2–5. | FR-07, FR-14 | `test_spec_ps_audience.py::test_ps_for_audience`, `test_spec_ps_audience.py::test_audience_keywords_keep_open_cases` |
| SPEC-KB-17 | THE SYSTEM SHALL хранить векторы фрагментов документов организации отдельно от текстов: нормированная float32-матрица на документ (`data/kb/vectors/<id>.npy`) с кэшем в памяти; WHEN index.json старого формата содержит векторы, THE SYSTEM SHALL перенести их в матрицы и убрать из JSON; WHEN администратор вызывает `POST /api/v1/kb/reindex`, THE SYSTEM SHALL догнать эмбеддингами документы без векторов. | FR-09, NFR (память контейнера) | `test_spec_kb_vectors.py::test_vectors_in_npy_migration_search_and_reindex` |
| SPEC-KB-18 | WHILE часть документов организации не имеет векторов, THE SYSTEM SHALL приводить оценки к одной шкале: фрагмент, найденный только по словам, получает не больше половины лучшего косинуса запроса, чтобы совпадение слов не вытесняло найденное по смыслу. | FR-09 | `test_spec_kb_vectors.py::test_mixed_index_keeps_semantic_hits_on_top` |
| SPEC-KB-19 | WHEN пользователь ищет в базе знаний (`POST /api/v1/kb/search`), THE SYSTEM SHALL сливать выдачу документов организации и выдачу выжимок норм по местам (reciprocal rank fusion), а не по сырым оценкам разных шкал; при равном месте документ организации идёт раньше. | FR-09 | `test_spec_kb_vectors.py::test_kb_search_fuses_org_and_norms_by_rank` |
| SPEC-KB-20 | WHEN запрос к базе знаний содержит сокращение образования (ДО, ДПО, ДООП, ДПП, СПО, ВО, ПС, ФГОС, ОВЗ, ГИА, ДОТ и др.) целым словом в верхнем регистре, THE SYSTEM SHALL дополнить запрос расшифровкой и для поиска по словам, и для эмбеддинга; строчное «до» не расширяется. | FR-09 | `test_spec_kb_vectors.py::test_abbreviations_expanded_in_search` |

## Вне области

- Реранкер и модель bge-m3 (в шлюзе хакатона их нет; используется Giga-Embeddings или поиск по словам).
- Автоматическое обновление реестров из внешних источников.
- Удаление записей дополнений `kb_*.json` через API.
