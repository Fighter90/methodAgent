# Развёртывание и эксплуатация

МетодАгент — один процесс uvicorn (FastAPI), который обслуживает API `/api/v1`, Swagger `/docs`, проверку `/health` и собранный интерфейс из `frontend/dist`; данные хранятся в SQLite и файлах каталога `data/runtime`. Запустить его можно локально (Python 3.12 + Node 22 для сборки интерфейса), в Docker через `docker-compose.yml` (скрипт `scripts/deploy_vm.sh`) или на ВМ без Docker (`scripts/run_vm.sh`). Демо-стенд: https://tochka-sborki-2026-team-098.hub.gigaschool.ru (вход через хаб хакатона), короткий адрес — https://methodagent.ru (редирект на адрес хаба).

## Локальный запуск

### Бэкенд

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt          # requirements.txt + pytest, hypothesis, ruff
cp .env.example .env                          # при необходимости задать LLM_API_KEY и др.
PYTHONPATH=src uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- Без ключа шлюза (или с `LLM_PROVIDERS=fixtures`) сервис работает на резервной генерации по шаблонам.
- При первом запуске создаются `data/runtime/`, БД `metodagent.db` (таблицы через `create_all`, миграций нет), `.secret_key` (если `SECRET_KEY` не задан) и демо-учётки.
- Если `frontend/dist/index.html` нет, на `/` отдаётся JSON с указанием на `/docs`.

### Интерфейс

```bash
cd frontend
npm ci
npm run dev        # Vite dev-сервер; /api, /health, /docs проксируются на 127.0.0.1:8000
npm run build      # tsc --noEmit && vite build → frontend/dist
```

После `npm run build` бэкенд сам раздаёт `frontend/dist` (`/assets/*` — статика, остальные пути — `index.html`, неизвестные `/api/*` — JSON 404).

## Docker

`Dockerfile` — двухэтапная сборка:

1. `node:22-alpine`: `npm ci`, `npm run build` интерфейса.
2. `python:3.12-slim`: установка `requirements.txt`, копирование `src`, `registry`, `testset`, `scripts`, собранного `frontend/dist`; пользователь `app` (uid 1000); `PYTHONPATH=/app/src`; порт 8000; `HEALTHCHECK` раз в 30 с запрашивает `http://127.0.0.1:8000/health`; команда `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips *`.

`docker-compose.yml` (сервис `app`, контейнер `metodagent`):

| Параметр | Значение |
|---|---|
| Порт | `0.0.0.0:8000:8000` |
| Перезапуск | `unless-stopped` |
| Окружение | `env_file: /opt/hackathon/ai.env`; `ENVIRONMENT=production`, `DATA_DIR=/app/data/runtime`, `SECRET_KEY`, `LLM_PROVIDERS`, `LLM_JUDGE_ENABLED` из окружения оболочки |
| Тома | `./data:/app/data`, `./logs:/app/logs` |
| Изоляция | `read_only: true`, `tmpfs /tmp` 256 МБ, `cap_drop: ALL`, `no-new-privileges`, `mem_limit: 2g`, `pids_limit: 256` (примеры кода из лекций выполняются в песочнице внутри контейнера) |

Файл `/opt/hackathon/ai.env` должен существовать на хосте; для запуска вне ВМ хакатона создайте его или уберите `env_file`.

```bash
docker compose up -d --build
docker compose logs -f app
```

## scripts/deploy_vm.sh

Развёртывание на ВМ через Docker:

1. Переходит в корень репозитория, создаёт `data/runtime` и `logs`.
2. Если в `.env` нет непустого `SECRET_KEY`, дописывает случайный (`secrets.token_hex(32)`) и ставит права 600.
3. Выбирает `docker compose` или `docker-compose` и выполняет `up -d --build`.
4. Включает `docker.service` (`sudo systemctl enable docker`, ошибки игнорируются) и добавляет в crontab строку `@reboot ... up -d` с меткой `metodagent-autostart` (старая строка с той же меткой заменяется).
5. До 60 секунд опрашивает `http://127.0.0.1:8000/health`; при успехе печатает ответ, иначе — последние 80 строк логов контейнера и выходит с кодом 1.

Примечание: `.env` читается `docker compose` для подстановки `${SECRET_KEY}` в `docker-compose.yml`, поэтому сгенерированный ключ попадает в контейнер.

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
