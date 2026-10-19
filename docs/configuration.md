# Конфигурация

Все настройки МетодАгента описаны в классе `Settings` (`src/app/core/config.py`, pydantic-settings) и читаются из переменных окружения и файлов `.env` и `/opt/hackathon/ai.env`; имена переменных нечувствительны к регистру, неизвестные переменные игнорируются. Часть настроек (ключ и адрес шлюза, модели, лимиты, вход, SSO, пароль почты) администратор может менять в интерфейсе на странице «Администрирование» без перезапуска: такие значения хранятся в таблице `settings` и перекрывают окружение (`src/app/core/runtime.py`), а секреты в ней зашифрованы ключом, производным от `SECRET_KEY` (`src/app/core/crypto.py`).

## Источники значений и приоритет

От низшего приоритета к высшему:

1. Значение по умолчанию в `Settings`.
2. Файлы окружения `.env` (в текущем каталоге процесса) и `/opt/hackathon/ai.env` — оба перечислены в `env_file`; при совпадении ключей pydantic-settings берёт значение из файла, указанного позже (`/opt/hackathon/ai.env`).
3. Переменные окружения процесса.
4. Значение, сохранённое администратором в таблице `settings` (только для полей из списка ниже). Применяется при старте (`runtime.load()` в `lifespan`) и сразу после сохранения (`runtime.update()`).

Объект настроек кэшируется (`get_settings()` с `lru_cache`); значения из админки записываются прямо в этот объект (`setattr`).

## Все настройки

### Общие

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` включает строгий режим ключа: если `SECRET_KEY` не задан и `DATA_DIR` недоступен для записи, запуск падает |
| `LOG_LEVEL` | `INFO` | Уровень журнала (`logging.basicConfig` в `lifespan`) |
| `APP_NAME` | `МетодАгент` | Название приложения |
| `APP_VERSION` | `0.1.0` | Версия, отдаётся в `/health` и OpenAPI |
| `API_V1_PREFIX` | `/api/v1` | Префикс API |
| `DOCS_ENABLED` | `true` | Swagger UI на `/docs` |

### Хранилище

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `DATA_DIR` | `<корень репозитория>/data/runtime` | Каталог рабочих данных: БД, ключ, правки реестров, база знаний, расход LLM |
| `DATABASE_URL` | пусто | URL SQLAlchemy; если пусто — `sqlite+aiosqlite:///<DATA_DIR>/metodagent.db` |
| `MAX_FILE_SIZE_MB` | `20` | Максимальный размер одного референса |
| `MAX_FILES_PER_REQUEST` | `5` | Максимум файлов в запросе на создание программы |

### Авторизация

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `SECRET_KEY` | `dev-secret-change-me` | Ключ подписи JWT и вывода ключа шифрования секретов (см. ниже) |
| `JWT_ALGORITHM` | `HS256` | Алгоритм JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | Срок жизни токена входа, мин |

### LLM

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `LLM_API_KEY` (синонимы `CLOUDRU_API_KEY`, `OPENAI_API_KEY`) | пусто | Ключ OpenAI-совместимого шлюза |
| `LLM_BASE_URL` (синонимы `CLOUDRU_BASE_URL`, `OPENAI_BASE_URL`) | `https://foundation-models.api.cloud.ru/v1` | Адрес шлюза |
| `LLM_MODEL_GENERATE` | `GigaChat/GigaChat-3-Pro` | Модель каркаса и содержания |
| `LLM_MODEL_JUDGE` | `ai-sage/GigaChat3.5-432B-A28B-Reasoning` | Модель-судья |
| `LLM_MODEL_RESERVE` | `GigaChat/GigaChat-3-Pro` | Резервная модель |
| `LLM_MODEL_EMBED` | `ai-sage/Giga-Embeddings-instruct-3B` | Модель эмбеддингов (поиск по базе знаний) |
| `LLM_CONCURRENCY` | `2` | Одновременных запросов к шлюзу |
| `LLM_TIMEOUT_S` | `120.0` | Таймаут запроса к модели, с |
| `LLM_PROVIDERS` | `cloudru` | `cloudru` — работа через шлюз; `fixtures` — без сети, детерминированные ответы навыков |
| `LLM_JUDGE_ENABLED` | `true` | Включить судью для смысловых правил V-21, V-22, V-26, V-27 |
| `LLM_PRICE_IN_RUB` / `LLM_PRICE_OUT_RUB` | `73.03` / `176.39` | Тариф модели генерации, ₽ за 1 млн токенов (вход/выход), для отчёта о стоимости |
| `LLM_JUDGE_PRICE_IN_RUB` / `LLM_JUDGE_PRICE_OUT_RUB` | `96.22` / `288.60` | Тариф судьи |
| `LLM_DAILY_BUDGET_RUB` | `90.0` | Дневной бюджет; после порога навыки переходят на резервную генерацию. Сутки считаются по МСК, сброс в 00:00 МСК |
| `GEN_WORKERS` | `6` | Потоков сборки модулей (фактически используется `max(4, GEN_WORKERS)`) |
| `ANON_RUNS_PER_HOUR` | `12` | Автопрогонов без токена в час с одного IP |
| `MAX_PARALLEL_JOBS` | `4` | Одновременных фоновых заданий; сверх — ответ 429 |

LLM считается включённой (`llm_enabled`), если `LLM_PROVIDERS=cloudru` и ключ не пуст.

### Вход, регистрация, SSO, почта

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `REGISTRATION_ENABLED` | `true` | Открыта ли самостоятельная регистрация |
| `REGISTRATION_DEFAULT_ROLE` | `expert` | Роль нового пользователя (`expert`, `methodist`, `head`) |
| `DEMO_ACCOUNTS_ENABLED` | `true` | Демо-учётки и переключатель ролей; при `false` токены демо-учёток (кроме `u-api`, `u-admin`) отклоняются |
| `SSO_ENABLED` | `false` | Показывать кнопку SSO (заготовка: протокол не подключён) |
| `SSO_PROVIDER` | `oidc` | `oidc` или `saml` |
| `SSO_DISPLAY_NAME` | `Единый вход организации` | Текст кнопки |
| `SSO_ISSUER_URL`, `SSO_CLIENT_ID`, `SSO_CLIENT_SECRET` | пусто | Параметры провайдера |
| `SMTP_PASSWORD` | пусто | Пароль почты для уведомлений; сервер, порт, логин и отправитель — в профиле организации |

## Настройки, изменяемые из админки

`GET /api/v1/admin/settings` возвращает группы и поля, `PUT /api/v1/admin/settings` принимает `{"values": {...}, "clear": [...]}` (роль `admin`). Список полей — `FIELDS` в `src/app/core/runtime.py`:

| Группа | Ключи | Тип и ограничения |
|---|---|---|
| Модель и ключи | `llm_providers` (choice: cloudru, fixtures), `llm_base_url`, `llm_api_key` (secret), `llm_model_generate`, `llm_model_judge`, `llm_model_reserve`, `llm_model_embed`, `llm_judge_enabled` (bool) | — |
| Лимиты | `llm_concurrency` 1–16, `gen_workers` 1–32, `llm_timeout_s` 5–900, `llm_daily_budget_rub` 0–1 000 000, `max_parallel_jobs` 1–64, `anon_runs_per_hour` 0–10 000 | int/float с проверкой диапазона |
| Вход и регистрация | `registration_enabled`, `registration_default_role` (expert, methodist, head), `demo_accounts_enabled`, `access_token_expire_minutes` 15–43 200 | — |
| SSO | `sso_enabled`, `sso_provider` (oidc, saml), `sso_display_name`, `sso_issuer_url`, `sso_client_id`, `sso_client_secret` (secret) | — |
| Почта | `smtp_password` (secret) | — |

Правила работы (`runtime.update`, `runtime.describe`):

- Значение приводится к типу поля и проверяется по диапазону или списку вариантов; ошибка — 400 с указанием ключа.
- Для секретов пустое значение или строка, начинающаяся с `••••` (маска), означает «не менять».
- Ключ из `clear` удаляет строку из таблицы `settings` и возвращает значение, которое было до первого переопределения в этом процессе (значение окружения).
- `describe()` для каждого поля сообщает источник: `admin`, `env` (непустое значение не из админки, в том числе значение по умолчанию) или `none`. Секреты отдаются только маской `••••` + последние 4 символа (если длина больше 8) и флагом `set`.
- После любого изменения сбрасывается клиент LLM (`llm.client._client = None`), поэтому новый ключ, адрес или лимит действует со следующего запроса.
- Изменение записывается в журнал (`audit_events`, `program_id='org'`) списком названий полей, без значений.
- Настройки, не входящие в `FIELDS` (`DATA_DIR`, `DATABASE_URL`, `SECRET_KEY`, тарифы, `ENVIRONMENT` и др.), меняются только через окружение и требуют перезапуска.

## Шифрование секретов

`src/app/core/crypto.py` использует только стандартную библиотеку:

- из `SECRET_KEY` через PBKDF2-HMAC-SHA256 (соль `metodagent-settings`, 200 000 итераций) выводится мастер-ключ, из него — ключ шифрования и ключ MAC;
- шифр — поток HMAC-SHA256 в режиме счётчика со случайным 16-байтным nonce, целостность — HMAC-SHA256 над nonce и шифртекстом;
- формат хранения: `enc1:` + base64url(nonce ‖ tag ‖ шифртекст).

Если `SECRET_KEY` сменился, секрет не расшифруется: при старте в журнал пишется предупреждение и используется значение из окружения; секрет нужно ввести в админке заново.

## SECRET_KEY

- Если `SECRET_KEY` короче 16 символов или содержит `change-me` (в том числе значение по умолчанию), при создании настроек генерируется случайный ключ (`secrets.token_hex(32)`) и сохраняется в `DATA_DIR/.secret_key` с правами 600; при следующих запусках он читается оттуда.
- Если записать ключ не удалось: в `production` запуск падает, в остальных окружениях используется исходная (небезопасная) строка.
- `scripts/deploy_vm.sh` и `scripts/run_vm.sh` дописывают случайный `SECRET_KEY` в `.env`, если его там нет.
- Смена ключа делает недействительными все выданные токены и зашифрованные в БД секреты.

## Файлы окружения

| Файл | Назначение |
|---|---|
| `.env.example` | Образец: `SECRET_KEY`, `LLM_PROVIDERS`, `LLM_JUDGE_ENABLED`, закомментированные `LLM_BASE_URL`, `LLM_API_KEY`, модели |
| `.env` | Локальные значения; в git не попадает (`.gitignore`), в образ не копируется (`.dockerignore`) |
| `/opt/hackathon/ai.env` | Ключ и адрес шлюза на ВМ (`OPENAI_API_KEY`, `OPENAI_BASE_URL`); читается `Settings`, подключается как `env_file` в `docker-compose.yml` и через `source` в `run_vm.sh` |

В `docker-compose.yml` дополнительно задаются `ENVIRONMENT=production`, `DATA_DIR=/app/data/runtime`, а `SECRET_KEY`, `LLM_PROVIDERS`, `LLM_JUDGE_ENABLED` пробрасываются из окружения оболочки (по умолчанию пусто, `cloudru`, `true`).

## Прочие переменные

`SMTP_PASSWORD` дополнительно читается напрямую из `os.environ` в `programs/service.py` как запасной вариант, если пароль не задан в настройках.
