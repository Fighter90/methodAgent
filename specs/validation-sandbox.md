# Песочница примеров кода

Префикс требований: `SPEC-SANDBOX`. Код: `src/app/validation/sandbox.py`. Подробности — [docs/validation.md](../docs/validation.md#песочница-sandboxpy). Тесты: `tests/test_spec_sandbox.py`.

## Назначение

Выполнение примеров кода из лекций в отдельном процессе без сети, с лимитами времени, CPU и памяти (правило V-24, отчёт песочницы FR-46). Примеры, обращающиеся к системе, не запускаются; примеры с тяжёлыми библиотеками проверяются только на синтаксис.

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-SANDBOX-01 | IF пример пуст, THEN THE SYSTEM SHALL не запускать его и вернуть `ok=True`, режим `skip`. | код | `test_spec_sandbox.py::test_empty_code_skipped` |
| SPEC-SANDBOX-02 | IF пример обращается к системе, сети, файлам, dunder-атрибутам или вызывает `eval`/`exec`/`open` и подобные (в том числе импортирует `io`, `runpy`, `code`, `operator` — аудит 19.10), THEN THE SYSTEM SHALL не запускать его и вернуть режим `skip` с сообщением «проверьте вручную». | V-24 | `test_spec_sandbox.py::test_system_access_not_run` |
| SPEC-SANDBOX-03 | IF пример импортирует тяжёлую библиотеку (pandas, numpy, matplotlib, seaborn, sklearn, requests, sqlalchemy) или использует sqlite3, THEN THE SYSTEM SHALL только скомпилировать его (режим `syntax`) и при синтаксической ошибке вернуть «Синтаксическая ошибка: … (строка N)». | V-24 | `test_spec_sandbox.py::test_heavy_libraries_syntax_only` |
| SPEC-SANDBOX-04 | THE SYSTEM SHALL определять импортируемые библиотеки примера без повторов в порядке появления. | FR-46 | `test_spec_sandbox.py::test_libraries_detected_in_order` |
| SPEC-SANDBOX-05 | WHEN пример допускает запуск, THE SYSTEM SHALL выполнить его в отдельном процессе `python -I` во временном каталоге с подачей ввода `5\n5\n5\n` и вернуть stdout (до 800 символов), время и режим `run`. | V-24, FR-46 | `test_spec_sandbox.py::test_run_success_stdout_and_input` |
| SPEC-SANDBOX-06 | IF процесс завершился с ненулевым кодом, THEN THE SYSTEM SHALL вернуть `ok=False` и последнюю строку stderr (до 200 символов). | V-24 | `test_spec_sandbox.py::test_run_error_last_stderr_line` |
| SPEC-SANDBOX-07 | THE SYSTEM SHALL запускать пример с минимальным окружением без переменных родителя, с прокси на недоступный адрес и таймаутом 10 с. | V-24, NFR-10 | `test_spec_sandbox.py::test_network_is_blocked` |
| SPEC-SANDBOX-08 | IF пример выполняется дольше 10 с, THEN THE SYSTEM SHALL вернуть `ok=False`, «Пример выполняется дольше 10 с» и время 10 с. | V-24 | `test_spec_sandbox.py::test_timeout_reported` |
| SPEC-SANDBOX-09 | THE SYSTEM SHALL возвращать из `run_snippet` `None` при успехе и текст ошибки при сбое. | код | `test_spec_sandbox.py::test_run_snippet` |
| SPEC-SANDBOX-10 | WHEN проверяются примеры комплекта, THE SYSTEM SHALL выполнить не больше `limit` (по умолчанию 12) примеров по порядку лекций и вернуть ошибки в виде «Пример к лекции <название>: <ошибка>». | V-24 | `test_spec_sandbox.py::test_check_examples_limit_and_messages` |
| SPEC-SANDBOX-11 | THE SYSTEM SHALL брать лимит времени и памяти дочернего процесса из `SANDBOX_TIMEOUT_S` и `SANDBOX_MEMORY_MB` (по умолчанию 10 с и 512 МБ) и сообщать о превышении времени фактическим лимитом. | ТЗ 4.11 (T-11, T-15) | `test_spec_sandbox.py::test_limits_from_settings` |
| SPEC-SANDBOX-12 | WHEN платформа отвергает установку лимита дочернего процесса (например, `RLIMIT_AS` на macOS — ValueError «current limit exceeds maximum limit»), THEN THE SYSTEM SHALL пропустить только этот лимит, всё равно выполнить пример (`ok=True`, режим `run`) и перечислить отвергнутые лимиты в `skipped_limits` результата. | аудит 19.10 (MET-17) | `test_spec_sandbox.py::test_limits_degrade_on_macos` |
| SPEC-SANDBOX-13 | THE SYSTEM SHALL возвращать в результате `run_detailed` списки `applied_limits` и `skipped_limits` — имена констант `resource`, которые удалось и не удалось установить дочернему процессу; для режимов `skip` и `syntax` оба списка пустые. | аудит 19.10 (MET-23, F01) | `test_spec_sandbox.py::test_limits_reported` |
| SPEC-SANDBOX-14 | WHEN пример содержит импорты вне разрешённого списка учебных модулей или обращается к dunder-атрибутам/именам, THEN THE SYSTEM SHALL не исполнять его (режим syntax) с сообщением о запрещённых конструкциях — AST-анализ закрывает обходы regex-фильтра (цепочки dunder-доступа, частичные импорты). | аудит 22.10 (R01-промежуточно) | `test_spec_sandbox.py::test_ast_allowlist_blocks_escape_vectors` |

## Вне области

Отчёт песочницы `extras.sandbox_report`, исправление упавших примеров моделью (`workflow._fix_examples`). `_limits` выполняется в дочернем процессе и проверяется косвенно — через `_probe_limits` и тесты с monkeypatch на `resource.setrlimit`. Тесты с реальным запуском пропускаются (`pytest.skip`), если песочница недоступна в окружении.
