# Клиент моделей (слой LLM)

Префикс требований: `SPEC-LLM`. Код: `src/app/llm/client.py`. Подробности — [docs/llm.md](../docs/llm.md). Тесты: `tests/test_spec_llm_client.py`.

## Назначение

OpenAI-совместимый клиент шлюза Cloud.ru (ТЗ 4.11): роли `generate` и `judge` с резервной моделью, повторы при ошибках и невалидном JSON, проверка ответа Pydantic-схемой, учёт токенов и рублей, дневной бюджет и суточный лимит шлюза по Москве, эмбеддинги и проверочный запрос (NFR-07, NFR-08, NFR-14).

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-LLM-01 | WHEN разбирается ответ модели, THE SYSTEM SHALL убрать блоки `<think>` (в том числе оборванный), обрамление ```` ```json ````, текст до первой `{`/`[` и после последней `}`/`]`, висячие запятые; IF JSON не найден, THEN THE SYSTEM SHALL бросить `JSONDecodeError`. | NFR-08 | `test_spec_llm_client.py::test_parse_json_cleanup`, `test_extras.py::test_parse_json_truncated_reasoning` |
| SPEC-LLM-02 | THE SYSTEM SHALL считать ошибку суточным лимитом только при статусе 429 и признаке `daily`, `spending limit` или `llm_daily_limit` в тексте или теле ошибки. | NFR-08 | `test_spec_llm_client.py::test_daily_limit_detection` |
| SPEC-LLM-03 | THE SYSTEM SHALL накапливать в `CallStats` входные и выходные токены, рубли и число вызовов, в том числе в разбивке по навыкам. | NFR-14 | `test_spec_llm_client.py::test_call_stats_accumulate` |
| SPEC-LLM-04 | IF модель не настроена, суточный лимит отмечен сегодня или расход за сутки не меньше `llm_daily_budget_rub`, THEN THE SYSTEM SHALL бросить `LLMUnavailable` без обращения к шлюзу. | NFR-08, NFR-14 | `test_spec_llm_client.py::test_disabled_and_budget_guards` |
| SPEC-LLM-05 | WHEN модель ответила, THE SYSTEM SHALL проверить JSON схемой навыка (или вернуть разобранный JSON без схемы), посчитать стоимость `(вход × цена_входа + выход × цена_выхода) / 10⁶`, добавить её в `CallStats` и в суточный расход в `data_dir/llm_spend.json` и отметить статус роли. | ТЗ 4.11, NFR-14 | `test_spec_llm_client.py::test_success_validates_and_accounts` |
| SPEC-LLM-06 | WHEN ответ не прошёл разбор или схему, THE SYSTEM SHALL отправить модели её ответ (до 6000 символов) и текст ошибки (до 800 символов) с просьбой вернуть исправленный JSON, считая это одной из попыток. | NFR-08 | `test_spec_llm_client.py::test_invalid_json_feedback_then_success` |
| SPEC-LLM-07 | IF ответ пустой (только рассуждение), THEN THE SYSTEM SHALL повторить исходный запрос без сообщения ассистента. | NFR-08 | `test_spec_llm_client.py::test_empty_answer_repeats_original` |
| SPEC-LLM-08 | WHEN шлюз вернул 5xx или сетевую ошибку, THE SYSTEM SHALL повторить запрос до 3 попыток с паузами 1 и 3 с, затем перейти к резервной модели; IF не ответила ни одна модель, THEN THE SYSTEM SHALL бросить `LLMUnavailable` «модель не ответила (<тип ошибки>)». | NFR-08 | `test_spec_llm_client.py::test_server_errors_retry_then_reserve` |
| SPEC-LLM-09 | WHEN шлюз вернул 401 или 403, THE SYSTEM SHALL сразу перейти к резервной модели без повторов. | NFR-08 | `test_spec_llm_client.py::test_auth_error_goes_to_reserve` |
| SPEC-LLM-10 | WHEN шлюз вернул 429 без признака суточного лимита, THE SYSTEM SHALL выдержать паузу 15 × (номер попытки + 1) с перед обычной паузой и повтором. | NFR-08 | `test_spec_llm_client.py::test_overload_429_backoff` |
| SPEC-LLM-11 | WHEN шлюз сообщил о суточном лимите, THE SYSTEM SHALL отметить лимит до 00:00 МСК с сохранением в файл, бросить `LLMUnavailable` без повторов и резерва и не обращаться к шлюзу при следующих вызовах. | NFR-08 | `test_spec_llm_client.py::test_daily_limit_no_retries`, `test_extras.py::test_daily_limit_fails_fast` |
| SPEC-LLM-12 | WHEN вызывается роль `judge`, THE SYSTEM SHALL сделать одну попытку моделью судьи, затем использовать модель генерации как резерв и считать стоимость по тарифу судьи; IF основная и резервная модели совпадают, THEN THE SYSTEM SHALL использовать одну модель. | ТЗ 4.11 | `test_spec_llm_client.py::test_judge_role_single_attempt_then_generate` |
| SPEC-LLM-13 | IF активное время запросов навыка достигло его бюджета, THEN THE SYSTEM SHALL бросить `LLMUnavailable` «бюджет времени … исчерпан» без нового запроса. | FR-19, FR-31 | `test_spec_llm_client.py::test_time_budget_exhausted` |
| SPEC-LLM-14 | THE SYSTEM SHALL вычислять бюджет времени навыка как `timeout_s × (retries + 1)` из `SKILL.md`, а для навыка без `SKILL.md` — как `llm_timeout_s × 3`. | FR-19, FR-31 | `test_spec_llm_client.py::test_budget_from_skill_md` |
| SPEC-LLM-15 | THE SYSTEM SHALL сохранять суточный расход между перезапусками, обнулять его с наступлением новых суток по Москве и запускаться при повреждённом файле расхода. | NFR-14 | `test_spec_llm_client.py::test_spend_persists_and_resets_daily`, `test_extras.py::test_budget_day_is_moscow` |
| SPEC-LLM-16 | IF файл расхода нельзя записать, THEN THE SYSTEM SHALL продолжить работу без исключения. | код | `test_spec_llm_client.py::test_spend_write_failure_tolerated` |
| SPEC-LLM-17 | WHEN запрошены эмбеддинги, THE SYSTEM SHALL отправлять тексты пачками по 16 и учитывать входные токены под именем `embed` со стоимостью 0. | FR-09 | `test_spec_llm_client.py::test_embed_batches` |
| SPEC-LLM-18 | IF модель не настроена или суточный лимит исчерпан, THEN THE SYSTEM SHALL бросить `LLMUnavailable` при запросе эмбеддингов. | FR-09 | `test_spec_llm_client.py::test_embed_guards` |
| SPEC-LLM-19 | WHEN выполняется проверочный запрос, THE SYSTEM SHALL вернуть `enabled=False` и провайдера без модели; при успешном ответе — `ok`, модель и задержку со сбросом отметки лимита; при ответе «суточный лимит» — отметить лимит и вернуть `daily_limit_reached`. | код | `test_spec_llm_client.py::test_ping` |
| SPEC-LLM-20 | THE SYSTEM SHALL создавать OpenAI-клиент лениво с адресом, ключом и таймаутом из настроек и без встроенных повторов, а `get_llm` — возвращать один экземпляр клиента на процесс. | ТЗ 4.11 | `test_spec_llm_client.py::test_openai_client_lazy_and_singleton` |

## Известные расхождения

- Докстринг модуля обещает, что после 429 параллельность «временно снижается»; в коде есть только пауза, семафор не меняется (отмечено и в docs/llm.md). Поведение кода (только пауза) зафиксировано в SPEC-LLM-10; отдельного требования на снижение параллельности нет.

## Вне области

Реальные задержки и лимиты шлюза, логирование (кроме того, что ключ и тексты не пишутся — не проверяется тестами), выбор моделей в настройках, параллелизм семафора.
