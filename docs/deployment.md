# Развёртывание и эксплуатация

МетодАгент — один процесс uvicorn (FastAPI), который обслуживает API `/api/v1`, Swagger `/docs`, проверку `/health` и собранный интерфейс из `frontend/dist`; данные хранятся в SQLite и файлах каталога `data/runtime`. Запустить его можно локально (Python 3.12 + Node 22 для сборки интерфейса, `scripts/run_local.sh`), в Docker через `docker-compose.yml` (на ВМ — скрипт `scripts/deploy_vm.sh`) или на ВМ без Docker (`scripts/run_vm.sh`). Версии интерпретаторов, базовых образов и всех пакетов зафиксированы (см. «Фиксация версий»), основной сценарий воспроизводится по шагам из раздела «Воспроизведение основного сценария». Демо-стенд: https://tochka-sborki-2026-team-098.hub.gigaschool.ru (вход через хаб хакатона), короткий адрес — https://methodagent.ru (редирект на адрес хаба).

## Фиксация версий

Повторный прогон через неделю или на другой машине ставит те же байты:

| Что | Где зафиксировано | Как обновить |
|---|---|---|
| Python | `.python-version` (3.12); в образе `python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1` | `docker buildx imagetools inspect python:3.12-slim` → новый `Digest` в `Dockerfile` |
| Node | `.nvmrc` (22), `frontend/package.json → engines` (`node >=22 <23`, `npm >=10`); в образе `node:22.23.3-alpine3.24@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402` | то же для `node:22-alpine` |
| Пакеты Python | `requirements.txt` — прямые зависимости (правятся руками), `requirements.lock` — все транзитивные с `==` и `--hash=sha256` | `uv pip compile requirements.txt --universal --python-version 3.12 --generate-hashes -o requirements.lock` |
| Пакеты для тестов | `requirements-dev.txt` → `requirements-dev.lock` | `uv pip compile requirements-dev.txt --universal --python-version 3.12 --generate-hashes -o requirements-dev.lock` |
| Пакеты интерфейса | `frontend/package-lock.json` (версии и `integrity`) | `npm install <пакет>` в `frontend/`, затем коммит lock-файла |

Установка всегда идёт с проверкой хэшей: `pip install --require-hashes -r requirements.lock` (так делают `Dockerfile` и `scripts/run_local.sh`) и `npm ci`, который падает при расхождении `package.json` и `package-lock.json`. Lock-файлы универсальные (маркеры платформ сохранены) и подходят для Linux, macOS и Windows. Совместимость lock-файлов с `requirements.txt` проверяет тест `tests/test_reproducibility.py`.

## Воспроизведение основного сценария

Основной сценарий: вход методиста, автопрогон запроса из `testset/cases.json`, проверка 10/10 блокирующих правил, скачивание выгрузок. Его можно повторить тремя способами. Команды выполняются из корня репозитория.

### А. Без Docker и без ключа LLM (детерминированно)

Режим `LLM_PROVIDERS=fixtures`: навыки отвечают по встроенным шаблонам и библиотеке типовых структур, сеть нужна только для установки пакетов, результат одинаков от прогона к прогону.

**Одной командой:**

```bash
bash scripts/run_local.sh            # PORT=8765 bash scripts/run_local.sh — другой порт
# ещё короче: make demo — поднимает сервер на фикстурах (порт 8765) и прогоняет кейс 1 с итогом на экране
```

Скрипт выполняет шаги 1–4 ниже. Окружение переустанавливается только при изменении `requirements.lock`, а интерфейс собирается, только если нет `frontend/dist/index.html`. Начало вывода:

```
== Создаю окружение /…/metodagent/.venv (Python 3.12.x)
== Ставлю зависимости из requirements.lock (--require-hashes)
== Собираю интерфейс (Node v22.x): npm ci && npm run build
✓ built in …
== Режим LLM_PROVIDERS=fixtures, данные: /…/metodagent/data/runtime
== Открыть: http://127.0.0.1:8000  (вход madina / demo), API: http://127.0.0.1:8000/docs
… INFO metodagent: МетодАгент запущен: LLM выключена (резервная генерация), навыков 11
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

**То же вручную:**

```bash
# 1. Окружение строго по lock-файлу
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock        # для тестов: requirements-dev.lock
# 2. Интерфейс
(cd frontend && npm ci && npm run build)                                     # → frontend/dist
# 3. Сервер в режиме fixtures
LLM_PROVIDERS=fixtures PYTHONPATH=src .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
# 4. Проверка (в другом терминале)
curl -s http://127.0.0.1:8000/health          # {"status":"ok","version":"0.1.0","llm":false}
```

**Интерфейс:** http://127.0.0.1:8000, вход `madina` / `demo` (методист). Дальше: «Новая программа», вставить запрос из `testset/cases.json`, ответить на вопросы, утвердить каркас и собрать комплект.

**Автопрогон через API** (без авторизации, лимит 12 запусков в час с одного IP):

```bash
curl -s -X POST 'http://127.0.0.1:8000/api/v1/programs?mode=auto' \
  -H 'Content-Type: application/json' \
  -d '{"request": "Программа ПК «Анализ данных на Python», 72 часа, 4 недели, итог — защита проекта"}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(r['status'], r['report']['blocking_checks'], r['skeleton']['totals']['all'], 'ч'); print(r['files']['docx'])"
```

Ожидается:

```
done 10/10 72 ч
http://127.0.0.1:8000/api/v1/programs/prg-…/export/docx
```

Ответ содержит поля `program_id`, `status`, `assumptions`, `questions_skipped`, `skeleton` (тип, часы, модули, календарь), `kit` (комплект по схеме 4.8), `report` (27 правил, `blocking_checks`, матрица покрытия), `agent_notes`, `files` (семь ссылок на выгрузки), `timing_s`, `tokens` и `effect`.

**Дымовая проверка** `scripts/smoke.sh` проходит весь путь: `/health`, вход `madina`/`demo`, автопрогон кейса из testset с токеном методиста, проверка `status` и `10/10`, `GET` каждой ссылки из `files`:

```bash
bash scripts/smoke.sh                                    # BASE_URL=http://127.0.0.1:8765 CASE=3 — другой адрес и кейс
bash scripts/smoke.sh --strict                           # строгий режим (или STRICT=1): статус обязан быть done
```

По умолчанию допустим статус `done_with_errors` (резервная генерация). В строгом режиме `--strict` любой статус, кроме `done`, — провал с кодом 1: так прогоняют приёмку перед показом.

```
1) GET http://127.0.0.1:8000/health
   {"status":"ok","version":"0.1.0","llm":false}
2) POST /api/v1/auth/login (madina / demo)
   роль: methodist, токен получен
3) POST /api/v1/programs?mode=auto — кейс 1 из testset/cases.json
   id=prg-… status=done за 0 с
   «Первые шаги в Python», тип doop, 16 ч, модулей 4
   блокирующие проверки 10/10, правил пройдено 27/27
   токены 0+0, 0.0 ₽; выгрузки: docx, pptx, gift, moodle_xml, json, order_draft, lectures_docx
4) Ссылки выгрузки (GET с токеном, ожидается 200)
   docx           HTTP 200     43807 байт
   …
   lectures_docx  HTTP 200     37462 байт
OK: основной сценарий пройден
```

При любом отклонении скрипт печатает `FAIL: …` и завершается с кодом 1.

**Пять открытых кейсов по чек-листам:**

```bash
.venv/bin/python scripts/autorun.py --url http://127.0.0.1:8000    # без --url — в процессе, сервер не нужен
```

```
Запрос 1: done, проверки 10/10, чек-лист 11/11, 0.1 с, 0.0 ₽
Запрос 2: done, проверки 10/10, чек-лист 9/9, 0.1 с, 0.0 ₽
Запрос 3: done, проверки 10/10, чек-лист 9/9, 0.2 с, 0.0 ₽
Запрос 4: done, проверки 10/10, чек-лист 9/9, 0.1 с, 0.0 ₽
Запрос 5: done, проверки 10/10, чек-лист 9/9, 0.2 с, 0.0 ₽
```

Полные ответы лежат в `logs/autorun/case<N>.json`, сводка — в `logs/autorun/summary.md`.

**Тесты** (окружение с dev-зависимостями):

```bash
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
PYTHONPATH=src .venv/bin/python -m pytest -q        # все тесты зелёные, сеть не нужна
```

### Б. Без Docker, с ключом Cloud.ru Foundation Models

Ключ задаётся в окружении или в `.env` в корне. Приложение читает `.env` и `/opt/hackathon/ai.env`, а значение ключа никуда не печатается.

```bash
export LLM_API_KEY='<ключ>'
export LLM_BASE_URL='https://foundation-models.api.cloud.ru/v1'     # или https://hub.gigaschool.ru/api/v1/llm/v1 (шлюз хакатона)
bash scripts/run_local.sh
```

Отличия от варианта А:

- в выводе стоит `Режим LLM_PROVIDERS=cloudru`, а `curl -s http://127.0.0.1:8000/health` возвращает `"llm": true`;
- `curl -s http://127.0.0.1:8000/api/v1/llm/status` показывает доступность шлюза (`ping`), модели и расход за сутки;
- в ответе автопрогона и в выводе `smoke.sh` токены и рубли больше нуля (`tokens.in`, `tokens.out`, `tokens.cost_rub`), время каждого этапа записано в `timing_s`; генерация занимает минуты;
- тексты лекций, тестов и заданий пишет модель `GigaChat/GigaChat-3-Pro`, а судья `ai-sage/GigaChat3.5-432B-A28B-Reasoning` оценивает комплект (отключается `LLM_JUDGE_ENABLED=false`).

Если ключ неверный, шлюз недоступен или дневной бюджет (`LLM_DAILY_BUDGET_RUB`) исчерпан, навыки переходят на резервную генерацию. Программа всё равно собирается со статусом `done` и `10/10`, а в журнале появляется `резервная генерация (LLMUnavailable …)`. Поэтому `smoke.sh` проходит и в этом случае. Убедиться, что работала модель, можно по `tokens.in > 0` в ответе.

### В. Docker Compose

Нужен Docker 24+ с плагином compose (или `docker-compose`). `docker-compose.yml` берёт `SECRET_KEY`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_PROVIDERS` и `LLM_JUDGE_ENABLED` из файла `.env` рядом с ним.

```bash
python3 - <<'PY'
import secrets, pathlib
p = pathlib.Path('.env')
p.write_text(f"SECRET_KEY={secrets.token_hex(32)}\nLLM_API_KEY=\nLLM_BASE_URL=https://foundation-models.api.cloud.ru/v1\n")
p.chmod(0o600)
PY
# впишите ключ в LLM_API_KEY= (пусто — резервная генерация; для явного офлайн-режима добавьте LLM_PROVIDERS=fixtures)
docker compose up -d --build
docker compose ps                      # STATUS: Up … (healthy) примерно через 30 с
curl -s http://127.0.0.1:8000/health   # {"status":"ok","version":"0.1.0","llm":true}  (false без ключа)
bash scripts/smoke.sh                  # тот же вывод, что в варианте А
docker compose logs -f app
```

Сборка двухэтапная, оба базовых образа закреплены по digest:

1. `node:22.23.3-alpine3.24@sha256:0a71…e402`: `npm ci` по `package-lock.json`, `npm run build`.
2. `python:3.12.15-slim-trixie@sha256:a6e3…11b1`: `pip install --require-hashes -r requirements.lock`, затем копирование `src`, `registry`, `testset`, `scripts` и собранного `frontend/dist`. Процесс работает от пользователя `app` (uid 1000) с `PYTHONPATH=/app/src` на порту 8000. `HEALTHCHECK` раз в 30 с запрашивает `/health`. Команда запуска: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips *`.

`docker-compose.yml` (сервис `app`, контейнер `metodagent`):

| Параметр | Значение |
|---|---|
| Порт | `0.0.0.0:8000:8000` |
| Перезапуск | `unless-stopped` |
| Окружение | `ENVIRONMENT=production`, `DATA_DIR=/app/data/runtime`; из `.env`: `SECRET_KEY`, `LLM_PROVIDERS` (по умолчанию `cloudru`), `LLM_API_KEY`, `LLM_BASE_URL` (по умолчанию `https://foundation-models.api.cloud.ru/v1`), `LLM_JUDGE_ENABLED` |
| Тома | `./data:/app/data`, `./logs:/app/logs` |
| Изоляция | `read_only: true`, `tmpfs /tmp` 256 МБ, `cap_drop: ALL`, `no-new-privileges`, `mem_limit: 2g`, `pids_limit: 256` (примеры кода из лекций выполняются в песочнице внутри контейнера) |

На ВМ команды `.env` вручную не создаётся: `./scripts/deploy_vm.sh` сам дописывает `SECRET_KEY`, а ключ и адрес шлюза переносит из `/opt/hackathon/ai.env` под именами `LLM_API_KEY` и `LLM_BASE_URL` (см. ниже).

### Разработка интерфейса

```bash
cd frontend
npm ci
npm run dev        # Vite dev-сервер; /api, /health, /docs проксируются на 127.0.0.1:8000
npm run build      # tsc --noEmit && vite build → frontend/dist
```

После `npm run build` бэкенд сам раздаёт `frontend/dist`: `/assets/*` — статика, остальные пути — `index.html`, неизвестные `/api/*` — JSON 404. Если `frontend/dist/index.html` нет, на `/` отдаётся JSON с указанием на `/docs`. При первом запуске создаются `data/runtime/`, БД `metodagent.db` (таблицы через `create_all`, миграций нет), `.secret_key` (если `SECRET_KEY` не задан) и демо-учётки.

## scripts/deploy_vm.sh

Развёртывание на ВМ через Docker:

1. Переходит в корень репозитория, создаёт `data/runtime` и `logs`.
2. Если в `.env` нет непустого `SECRET_KEY`, дописывает случайный (`secrets.token_hex(32)`) и ставит права 600.
3. Если `/opt/hackathon/ai.env` доступен для чтения, переносит из него ключ (`*API_KEY=`) и адрес (`*BASE_URL=`) в `.env` под именами `LLM_API_KEY` и `LLM_BASE_URL`, заменяя прежние строки; остальное содержимое файла хакатона в `.env` не попадает.
4. Выбирает `docker compose` или `docker-compose` и выполняет `up -d --build`.
5. Включает `docker.service` (`sudo systemctl enable docker`, ошибки игнорируются) и добавляет в crontab строку `@reboot ... up -d` с меткой `metodagent-autostart` (старая строка с той же меткой заменяется).
6. До 60 секунд опрашивает `http://127.0.0.1:8000/health`; при успехе печатает ответ, иначе — последние 80 строк логов контейнера и выходит с кодом 1.

Примечание: `.env` читается `docker compose` для подстановки `${SECRET_KEY}`, `${LLM_API_KEY}` и `${LLM_BASE_URL}` в `docker-compose.yml`, поэтому сгенерированный ключ и ключ шлюза попадают в контейнер.

## scripts/run_vm.sh

Запуск без Docker:

1. Создаёт `data/runtime`, `logs`; при необходимости дописывает `SECRET_KEY` в `.env` (как выше).
2. Создаёт `.venv` (если нет), обновляет pip, ставит `requirements.txt`.
3. Если нет `frontend/dist/index.html` и есть `npm` — собирает интерфейс; без `npm` предупреждает, что заработает только API.
4. Экспортирует переменные из `.env` и, если доступен для чтения, из `/opt/hackathon/ai.env`.
5. Останавливает предыдущий процесс `uvicorn app.main:app --host 0.0.0.0 --port 8000` и запускает новый через `nohup` с `PYTHONPATH=src`, `DATA_DIR=data/runtime`, `--proxy-headers`; вывод — в `logs/app.log`.
6. Регистрирует в crontab `@reboot ... bash scripts/run_vm.sh` (метка `metodagent-autostart`).
7. До 60 секунд проверяет `/health`; при неудаче печатает хвост `logs/app.log`.

## Публикация

- Стенд доступен через хаб хакатона: `https://tochka-sborki-2026-team-098.hub.gigaschool.ru`. У хаба свой вход; его прокси перехватывает запросы с заголовком `Authorization`, поэтому интерфейс передаёт токен приложения в `X-MA-Token`. API-клиенты, обращающиеся напрямую, используют `Authorization: Bearer`.
- `uvicorn` запускается с `--proxy-headers --forwarded-allow-ips *`: адрес клиента для лимита анонимных автопрогонов и `base_url` ссылок на выгрузки берутся из заголовков прокси.
- `methodagent.ru` обслуживается GitHub Pages (отдельный репозиторий с редиректом, сертификат Let's Encrypt, Enforce HTTPS) и переадресует на адрес хаба.

## Обновление

```bash
cd ~/project
git pull
./scripts/deploy_vm.sh        # пересборка образа и перезапуск; или scripts/run_vm.sh без Docker
```

- Схема БД создаётся `create_all` при старте: новые таблицы появятся сами, но изменения существующих столбцов не применяются (системы миграций нет). Код учитывает это: например, «было/стало» в журнале хранится внутри текста события, чтобы не менять схему таблицы.
- `data/runtime` (БД, ключ, правки реестров, документы и полные тексты актов базы знаний, правки навыков) лежит в томе и при выкладке не затирается.
- Незавершённые фоновые задания после перезапуска продолжаются автоматически (`resume_jobs`).

## Резервное копирование

Всё состояние — в `data/runtime/`:

| Файл | Содержимое |
|---|---|
| `metodagent.db` | Программы, версии, журнал, задания, уведомления, пользователи, настройки |
| `.secret_key` | Ключ, если `SECRET_KEY` не задан в окружении (без него не расшифруются секреты в БД и станут недействительны токены) |
| `registry/` | Правки реестров и профиля организации |
| `kb/` | Документы организации и полные тексты актов, загруженные администратором |
| `skills_overrides.json` | Параметры навыков, изменённые в админке |
| `llm_spend.json` | Расход LLM за текущие сутки |

Пример (на время копирования лучше остановить сервис, чтобы получить согласованный файл SQLite):

```bash
docker compose stop app
tar czf backup-$(date +%F).tgz data/runtime .env
docker compose start app
```

Альтернатива без остановки — `sqlite3 data/runtime/metodagent.db ".backup backup.db"`. Храните резервные копии вместе с `.env` (или `SECRET_KEY`) в защищённом месте.

## Журналы

| Режим | Где смотреть |
|---|---|
| Docker | `docker compose logs -f app` (stdout uvicorn и приложения) |
| Без Docker | `logs/app.log` |
| Автозапуск после перезагрузки | `logs/reboot.log` |
| Автопрогон | `logs/autorun/` |

Формат: `%(asctime)s %(levelname)s %(name)s: %(message)s`, уровень — `LOG_LEVEL`. Ключи API и тексты запросов к модели в журнал не пишутся.

Действия пользователей (создание, правки, решения, утверждения, изменения настроек) пишутся в таблицу `audit_events` и доступны через `GET /api/v1/programs/{id}/events` и `GET /api/v1/admin/journal`.

## Проверка состояния

| Метод | Ответ |
|---|---|
| `GET /health` | `{"status": "ok", "version": "...", "llm": true/false}` — используется в `HEALTHCHECK` и скриптах |
| `GET /api/v1/health` | То же под префиксом API |
| `GET /api/v1/llm/status` | Доступность шлюза (`ping`), модели, расход за сутки, дневной бюджет, флаг исчерпания лимита, включён ли судья |
| `GET /api/v1/skills` | Список загруженных навыков |

`"llm": false` в `/health` означает, что ключ шлюза не задан или выбран режим `fixtures`; сервис при этом работает на резервной генерации. Дневной лимит шлюза сбрасывается в 00:00 МСК.
