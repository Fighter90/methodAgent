# Клиент моделей (слой LLM)

Префикс требований: `SPEC-LLM`. Код: `src/app/llm/client.py`. Подробности — [docs/llm.md](../docs/llm.md). Тесты: `tests/test_spec_llm_client.py`.

## Назначение

Клиент шлюза Cloud.ru Evolution Foundation Models (httpx, без сторонних SDK) (ТЗ 4.11): роли `generate` и `judge` с резервной моделью, повторы при ошибках и невалидном JSON, проверка ответа Pydantic-схемой, учёт токенов и рублей, дневной бюджет и суточный лимит шлюза по Москве, эмбеддинги и проверочный запрос (NFR-07, NFR-08, NFR-14).

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
| SPEC-LLM-20 | THE SYSTEM SHALL создавать клиент шлюза Cloud.ru лениво с адресом, ключом и таймаутом из настроек и без встроенных повторов, а `get_llm` — возвращать один экземпляр клиента на процесс. | ТЗ 4.11 | `test_spec_llm_client.py::test_gateway_client_lazy_and_singleton` |
| SPEC-LLM-21 | THE SYSTEM SHALL учитывать вызовы в `CallStats` атомарно (`add` и `merge` под замком): параллельные задачи и потоки не теряют токены, рубли и число вызовов; `merge` переносит и отказы навыков. | NFR-08 | `test_spec_robustness.py::test_call_stats_threadsafe_and_merge` |
| SPEC-LLM-22 | WHEN запрошены эмбеддинги, THE SYSTEM SHALL ограничивать каждую пачку таймаутом и повторять её при сетевой ошибке, таймауте, 429 и 5xx с паузами 1 и 3 с; IF шлюз ответил 401/403 или «суточный лимит», THEN THE SYSTEM SHALL бросить `LLMUnavailable` без повторов. | NFR-08 | `test_spec_robustness.py::test_embed_retries_transient`, `test_spec_robustness.py::test_embed_no_retry_on_auth_and_limit` |
| SPEC-LLM-23 | THE SYSTEM SHALL ограничивать таймаутом и проверочный запрос `ping`; IF ответ шлюза не содержит `choices`, THEN THE SYSTEM SHALL считать его ошибкой транспорта и повторить по общим правилам, а наружу отдать только `LLMUnavailable`. | NFR-08 | `test_spec_robustness.py::test_ping_timeout_and_malformed_response` |
| SPEC-LLM-24 | IF ответ модели оборван (не разбирается как JSON) и исправления в пределах попыток и бюджета времени не помогли, а навык разрешил частичный ответ (`partial_ok`, навык content), THEN THE SYSTEM SHALL вернуть целую часть ответа, закрыв её по последнему целому значению, и записать отказ в `step_errors`; недостающее навык добирает по шаблону. | NFR-08, FR-31 | `test_spec_llm_client.py::test_truncated_answer_salvaged_when_partial_ok` |
| SPEC-LLM-25 | WHEN вызов ожидает освобождения семафора параллельности, THEN THE SYSTEM SHALL перепроверить дневной бюджет после захвата слота: вызов, стоявший в очереди в момент исчерпания бюджета, не отправляется к шлюзу. | NFR-14, аудит 19.10 (F15) | `test_spec_llm_client.py::test_budget_checked_after_queue` |
| SPEC-LLM-26 | THE SYSTEM SHALL кэшировать живую проверку `GET /llm/status` на 5 минут и опрашивать модель через общий семафор параллельности; администратору возвращается живая проверка по каждому запросу. | NFR-14, аудит 19.10 (F15) | `test_spec_misc.py::test_llm_status_cache_and_admin_live` |

## Таймауты, повторы и отказы (сводка)

- Таймаут есть у каждого внешнего вызова: httpx (`llm_timeout_s`), `asyncio.wait_for` в `complete_json` (не больше остатка бюджета навыка `timeout_s × (retries + 1)` из `SKILL.md`), в `embed` и в `ping` (≤ 30 с).
- Повторы: сеть, таймаут, 5xx, ответ без `choices` — паузы 1 и 3 с, затем резервная модель (SPEC-LLM-08, SPEC-LLM-23); 429 — паузы 15, 30 с; 401/403 — сразу резерв; суточный лимит — сразу `LLMUnavailable` до 00:00 МСК (SPEC-LLM-02, SPEC-LLM-22); эмбеддинги — те же паузы без резервной модели (SPEC-LLM-22).
- Наружу — только `LLMUnavailable`; навык ловит его и `MODEL_DATA_ERRORS`, переходит на резерв и пишет отказ в `CallStats.fallbacks` → `doc.step_errors` (SPEC-CONTENT-13, SPEC-FLOW-39).
- Подробно: [docs/llm.md](../docs/llm.md), раздел «Таймауты, повторы и отказы».

## Известные расхождения

- Докстринг модуля обещает, что после 429 параллельность «временно снижается»; в коде есть только пауза, семафор не меняется (отмечено и в docs/llm.md). Поведение кода (только пауза) зафиксировано в SPEC-LLM-10; отдельного требования на снижение параллельности нет.

## Вне области

Реальные задержки и лимиты шлюза, логирование (кроме того, что ключ и тексты не пишутся — не проверяется тестами), выбор моделей в настройках, параллелизм семафора.
