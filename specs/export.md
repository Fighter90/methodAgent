# Выгрузка комплекта

Префикс требований: `SPEC-EXPORT`. Код: `src/app/export/service.py`; эндпоинт `GET /programs/{id}/export/{fmt}` в `src/app/programs/router.py`. Подробности — [docs/export.md](../docs/export.md).

## Назначение

Выгрузка без модели в семь форматов: программа по шаблону АЦР (DOCX), лекции (DOCX), проект приказа (DOCX), слайды (PPTX), тесты (GIFT, Moodle XML), полный комплект (JSON по схеме 4.8 ТЗ). Реквизиты, ФИО и подписи остаются пустыми полями для людей.

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-EXPORT-01 | THE SYSTEM SHALL выгружать форматы `docx`, `pptx`, `gift`, `moodle_xml`, `json`, `order_draft`, `lectures_docx`; IF формат неизвестен, THEN THE SYSTEM SHALL ответить 400 со списком доступных. | FR-52 – FR-57 | `test_spec_export.py::test_formats_and_unknown` |
| SPEC-EXPORT-02 | WHEN запрашивается `docx`, THE SYSTEM SHALL вернуть документ Word (архив ZIP) по шаблону АЦР с титулом, разделами в порядке шаблона, таблицами учебного плана, УТП и календаря и приложениями. | FR-52, FR-25 | `test_core.py::test_open_cases_auto` |
| SPEC-EXPORT-03 | THE SYSTEM SHALL оставлять номер и дату приказа, ФИО преподавателей и подписи незаполненными полями из подчёркиваний (`________________`; в грифе титула — `№ ____ от «___» __________ 20__ г.`) во всех выгрузках. | FR-52, NFR-11 | `test_spec_export.py::test_human_fields_left_blank` |
| SPEC-EXPORT-04 | WHEN запрашивается `json`, THE SYSTEM SHALL вернуть объект `program` по схеме 4.8 (id, тип, объём, компетенции с индикаторами и РО, модули с часами `total/lk/pr/lb/srs`, вопросы, задания, лекции, итоговая аттестация) без служебных полей `usage` и `params`. | FR-57 | `test_access.py::test_json_export_follows_schema_48` |
| SPEC-EXPORT-05 | WHEN запрашиваются тесты, THE SYSTEM SHALL выгружать GIFT с экранированием служебных символов и Moodle XML с вопросами `multichoice` с одним верным ответом (`fraction="100"`). | FR-56 | `test_spec_export.py::test_gift_and_moodle_xml` |
| SPEC-EXPORT-06 | WHEN запрашивается `pptx`, THE SYSTEM SHALL вернуть презентацию 16:9 со слайдами лекций; IF слайдов нет, THEN THE SYSTEM SHALL выгрузить слайд «Структура программы». | FR-53 | `test_spec_export.py::test_pptx_16x9_and_fallback` |
| SPEC-EXPORT-07 | WHEN запрашиваются лекции, THE SYSTEM SHALL выгрузить план по минутам, примеры кода моноширинным шрифтом и тезисы слайдов. | FR-54, FR-28 | `test_spec_export.py::test_lectures_docx` |
| SPEC-EXPORT-08 | WHEN запрашивается проект приказа, THE SYSTEM SHALL сформировать его без номера, даты, ответственных и подписи, с пометкой об автоматическом формировании. | FR-52 | `test_spec_export.py::test_order_draft` |
| SPEC-EXPORT-09 | THE SYSTEM SHALL называть файл по названию программы (символы, кроме букв, цифр и дефиса, — `_`, до 60 символов) и отдавать его с `Content-Disposition: attachment`. | код | `test_spec_export.py::test_filename_and_disposition` |
| SPEC-EXPORT-10 | IF выгрузку запрашивает анонимный клиент к чужой программе, THEN THE SYSTEM SHALL ответить 401; IF эксперт, THEN 403. | FR-44, NFR-10 | `test_access.py::test_no_token_cannot_read_others`, `test_access.py::test_expert_sees_only_own_modules_and_accepts_items` |
| SPEC-EXPORT-11 | WHEN завершается автопрогон, THE SYSTEM SHALL включить в ответ ссылки на выгрузку во всех форматах. | FR-62 | `test_spec_export.py::test_auto_run_lists_all_exports` |
| SPEC-EXPORT-12 | WHEN выгружается DOCX программы ДПП ПК, THE SYSTEM SHALL использовать шапки образца АЦР: в учебном плане «Наименование разделов программы» и «Форма аттестации», в УТП «Наименование разделов, тем программы» и «Форма контроля». | FR-54, FR-25 | `test_tz_compliance.py::test_dpp_curriculum_and_utp_headers_follow_template` |
| SPEC-EXPORT-13 | WHEN выгружается DOCX программы ДООП, THE SYSTEM SHALL выводить в разделе 3.4 таблицу образца «№ · Модуль/Дисциплина в соответствии с УП · ФИО преподавателя · Уч. степень/Звание · Должность» по модулям учебного плана и итоговой аттестации с пустыми ФИО, степенью и должностью. | FR-54, NFR-11 | `test_tz_compliance.py::test_doop_staff_table_with_blank_names` |
| SPEC-EXPORT-14 | THE SYSTEM SHALL заключать текст вопроса и вариантов Moodle XML в CDATA с разрывом последовательности `]]>` (`]]]]><![CDATA[>`) и валидировать собранный XML парсером; IF собранный XML не разбирается, THEN THE SYSTEM SHALL ответить ошибкой вместо битого файла. | Доп. (аудит F18) | `test_spec_export.py::test_moodle_xml_cdata_roundtrip` |

## Вне области

- Выгрузка в PDF (не реализована).
- Заполнение реквизитов и подписей.
- Тексты разделов (собирает `sections.py`, см. [agent-workflow.md](agent-workflow.md)).
