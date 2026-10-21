# Сервис программ

Префикс требований: `SPEC-SVC`. Код: `src/app/programs/service.py`. Подробности — [docs/data-model.md](../docs/data-model.md), [docs/api.md](../docs/api.md). Тесты: `tests/test_spec_service.py`.

## Назначение

Слой хранения поверх SQLite/SQLAlchemy: загрузка и сохранение документа программы, версии-снимки, журнал событий «было / стало» (FR-58), уведомления в интерфейсе и по почте (FR-59), список программ с фильтрами руководителя (FR-50), фоновые задания с прогрессом, перезапуском после рестарта (NFR-08) и ограничением параллельности (ТЗ, таблица 20).

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-SVC-01 | THE SYSTEM SHALL выдавать идентификаторы вида «<префикс>-<10 hex-символов>» без повторов. | код | `test_spec_service.py::test_new_id_format` |
| SPEC-SVC-02 | WHEN документ сохраняется, THE SYSTEM SHALL обновить время изменения, подогнать хронометраж лекций под их длительность, сохранить владельца при первом сохранении и не менять его при последующих; `load` SHALL вернуть сохранённый документ. | FR-28 | `test_spec_service.py::test_save_and_load_roundtrip` |
| SPEC-SVC-03 | IF программа или версия не найдены, THEN THE SYSTEM SHALL бросить `NotFound` из `load`, `owner_of` и `version_doc`. | код | `test_spec_service.py::test_missing_program_not_found` |
| SPEC-SVC-04 | WHEN сохранение идёт со снимком, THE SYSTEM SHALL присвоить версию «максимум из текущей и сохранённых + 1» и записать снимок с причиной; `versions` SHALL перечислять снимки от новых к старым. | FR-58 | `test_spec_service.py::test_snapshots_increment_version` |
| SPEC-SVC-05 | WHEN пишется событие журнала, THE SYSTEM SHALL сохранить актёра, действие, текст, узел, «было / стало» и версию (по умолчанию — текущую версию программы или 1), а при чтении — подставить имя актёра и вернуть события от новых к старым. | FR-58 | `test_spec_service.py::test_events_with_before_after` |
| SPEC-SVC-06 | THE SYSTEM SHALL хранить уведомления по пользователю (новые сверху, до 30) и отмечать прочитанными все или выбранные, возвращая число отмеченных. | FR-59 | `test_spec_service.py::test_notifications_and_mark_read` |
| SPEC-SVC-07 | WHEN в профиле включены письма и у пользователя есть адрес, THE SYSTEM SHALL продублировать уведомление на почту. | FR-59 | `test_spec_service.py::test_notify_email_by_profile` |
| SPEC-SVC-08 | WHEN письмо отправляется, THE SYSTEM SHALL использовать SMTP из профиля со STARTTLS и логином; IF хост SMTP не задан, THEN THE SYSTEM SHALL не отправлять письмо; IF SMTP недоступен, THEN THE SYSTEM SHALL продолжить работу без исключения. | FR-59 | `test_spec_service.py::test_send_mail_smtp` |
| SPEC-SVC-09 | THE SYSTEM SHALL брать руководителя из профиля организации, иначе — всех пользователей с ролью `head`, а адрес пользователя искать среди экспертов, руководителя и методистов профиля. | FR-50 | `test_spec_service.py::test_head_ids_and_emails` |
| SPEC-SVC-10 | WHEN запрашивается список программ, THE SYSTEM SHALL фильтровать по владельцу и статусам, а период — по дате утверждения программы (иначе по дате изменения). | FR-50 | `test_spec_service.py::test_list_programs_filters` |
| SPEC-SVC-11 | WHEN задание создаётся и запускается, THE SYSTEM SHALL создать его в статусе `queued`, перевести в `running`, записывать прогресс и по завершении поставить `done`; незавершённые задания SHALL быть доступны для перезапуска. | NFR-08 | `test_spec_service.py::test_jobs_lifecycle` |
| SPEC-SVC-12 | IF задание завершилось исключением, THEN THE SYSTEM SHALL поставить статус `failed` и текст ошибки (`message_ru` или имя исключения, не длиннее 2000 символов); IF задания нет, THEN THE SYSTEM SHALL не менять ничего при обновлении и бросить `NotFound` при чтении. | NFR-08 | `test_spec_service.py::test_job_failure_recorded` |
| SPEC-SVC-13 | IF выполняется `max_parallel_jobs` заданий, THEN THE SYSTEM SHALL отклонить новое задание с `RateLimited` (429). | ТЗ, таблица 20 | `test_spec_service.py::test_check_capacity` |
| SPEC-SVC-14 | WHEN создаётся фоновое задание через `start_job`, THE SYSTEM SHALL сначала проверить лимит параллельных заданий (429 до создания записи) и вернуть уже активное задание программы, если оно есть, не создавая новое: на программе — один активный job. | аудит 19.10 (F05) | `test_spec_service.py::test_start_job_capacity_first_and_idempotent` |
| SPEC-SVC-15 | WHEN действие с зарезервированным заданием прервалось до его запуска, THEN `cancel_job` SHALL закрыть задание со статусом `failed`, освобождая место для следующего задания программы. | аудит 19.10 (F05) | `test_spec_service.py::test_start_job_capacity_first_and_idempotent` |
| SPEC-SVC-16 | WHEN документ сохраняется, THE SYSTEM SHALL подогнать хронометраж каждого плана лекции под его длительность; IF план одной лекции в неожиданном формате (например, минуты строкой), THEN THE SYSTEM SHALL сохранить документ, оставив этот план как есть, не прерывая сохранение ошибкой 500. | FR-28, демо-прогон 19.10 (MET-5) | `test_spec_service.py::test_save_survives_malformed_lecture_plan` |

## Вне области

Схема таблиц и миграции (`core/db.py`), права доступа к методам (см. [auth-and-roles.md](auth-and-roles.md)), реальная доставка почты, перезапуск заданий в lifespan.
