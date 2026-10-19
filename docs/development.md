# Разработка

Код приложения лежит в `src/app` и запускается с `PYTHONPATH=src`; тесты — pytest в `tests/` (настройки в `pytest.ini`: `pythonpath = src`, `testpaths = tests`, `asyncio_mode = auto`), линтер — ruff, сквозная проверка — `scripts/autorun.py` по пяти открытым запросам кейса из `testset/cases.json`. Тесты не ходят в сеть: они задают `LLM_PROVIDERS=fixtures` и временный `DATA_DIR`, поэтому навыки отвечают детерминированно, а БД создаётся заново. Ниже — что покрывает каждый файл тестов, правила для разработчиков и порядок расширения: навык, акт в реестре, правило проверки, страница интерфейса.

## Окружение

Версии: Python 3.12 (`.python-version`), Node 22 и npm 10+ (`.nvmrc`, `frontend/package.json → engines`). Пакеты ставятся из lock-файлов с хэшами, поэтому окружение совпадает с образом Docker и CI.

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock   # сервис + pytest 9.1.1, pytest-asyncio 1.4.0, hypothesis 6.170.1, ruff 0.17.1
cd frontend && npm ci                                   # ровно package-lock.json
```

С uv то же самое быстрее: `uv venv .venv --python 3.12 && VIRTUAL_ENV=.venv uv pip install --require-hashes -r requirements-dev.lock`.

Новая зависимость добавляется в `requirements.txt` (или `requirements-dev.txt`) с точной версией `==`, после чего lock-файлы пересобираются:

```bash
uv pip compile requirements.txt     --universal --python-version 3.12 --generate-hashes -o requirements.lock
uv pip compile requirements-dev.txt --universal --python-version 3.12 --generate-hashes -o requirements-dev.lock
```

Если lock-файл не обновлён, `tests/test_reproducibility.py` падает. Сервер для ручной проверки запускается так: `bash scripts/run_local.sh` (режим `fixtures`, если ключ LLM не задан); дымовой прогон основного сценария — `bash scripts/smoke.sh`. Подробно: [развёртывание](deployment.md#воспроизведение-основного-сценария).

## Тесты

```bash
pytest -q                     # все тесты
pytest -q tests/test_auth.py  # один файл
pytest -q -k skeleton         # по имени
```

Файлы с API-тестами (`test_access.py`, `test_auth.py`, `test_core.py`, `test_extras.py`) в начале выставляют `os.environ.setdefault('LLM_PROVIDERS', 'fixtures')` и в фикстуре уровня модуля задают `DATA_DIR` во временном каталоге.

| Файл | Тестов | Что покрывает |
|---|---|---|
| `tests/test_core.py` | 3 | Солвер часов (суммы метода наибольших остатков), автопрогон пяти открытых запросов кейса, роли |
| `tests/test_skeleton.py` | 6 | Каркас: хронометраж плана лекции (`fit_plan`), сопоставление ТФ по смыслу, проверка часов в PDF-референсе, ручные часы тем и допущения, решения по отдельным узлам «!», календарь по видам работы и планы лекций |
| `tests/test_access.py` | 10 | Права и жизненный цикл: 401 без токена, асинхронный автопрогон (202 и результат задания), эксперт видит только свои модули и принимает элементы, откат не возвращает утверждение, JSON-выгрузка по схеме 4.8, правка часов сохраняет итог модуля, приём модуля только после всех элементов, профиль/реестр администратора и подсказки экспертов, качество и владельцы у руководителя, неназначенный эксперт и 404 для API |
| `tests/test_auth.py` | 6 | Вход по логину и id, все демо-учётки; регистрация с минимальной ролью и личный кабинет; администратор ведёт пользователей, но не программы; секрет в настройках маскируется, шифруется и применяется; переключатели регистрации и демо-учёток; правка и сброс параметров навыка |
| `tests/test_extras.py` | 18 | Анонимный доступ только к автопрогону и чтению; адаптация, смена шаблона, актуализация, сравнение версий и разделы, песочница и задачи по ролям, фильтр руководителя, загрузка и поиск в базе знаний, защиты каркаса, repair для V-13, объединение замечаний судьи, источники для школ, вариативность вопросов собеседования, разбор усечённого JSON рассуждающей модели, вычищение заблокированных сервисов, быстрый отказ при дневном лимите, сутки бюджета по МСК, кириллический .txt |
| `tests/test_norms.py` | 5 | Нормативная база: утратившие силу акты не используются, обязательные акты и акты по ключевым словам, ПС для открытых кейсов, связь выжимок с реестром, `norm_base_for_level` для школы, колледжа, вуза |

Тесты по спецификациям SDD (`tests/test_spec_*.py`) проверяют требования из [`specs/`](../specs/README.md): солверы, правила V-05…V-27, выгрузку, repair, песочницу, судью, LLM-клиент, сервис программ, навыки content и review_assist, конвейер, API и права. Docstring каждого теста начинается с идентификатора требования (`SPEC-RULES-07: …`).

`tests/test_core.py` и `tests/test_skeleton.py` используют hypothesis (property-based проверки); `.hypothesis/` — его кэш.

### Покрытие

```bash
PYTHONPATH=src pytest -q --cov=src/app --cov-report=term
```

Порог задан в `.coveragerc` (`fail_under = 60`): прогон с покрытием падает, если оно ниже 60%. Сейчас 221 тест и покрытие 90%.

### SDD: спецификация → тест → код

1. Требование записывается в `specs/<модуль>.md` в формате EARS (ТЗ 4.11) с идентификатором `SPEC-<МОДУЛЬ>-NN` и ссылкой на FR/NFR ТЗ.
2. Пишется тест, docstring которого начинается с этого идентификатора; имя теста вносится в столбец «Тест» спецификации.
3. Пишется или правится код, пока тест не станет зелёным.
4. `python scripts/spec_trace.py` показывает требования без тестов и падает с кодом 1, если тест ссылается на несуществующий идентификатор. `--markdown` перегенерирует сводную таблицу в `specs/README.md`.

Сейчас 257 требований в 16 спецификациях, 236 из них проверяются тестами. Без автотестов только требования к интерфейсу (`specs/frontend.md`) и SPEC-KB-13. Подробности процесса — в [`specs/README.md`](../specs/README.md).

## Линтер

```bash
ruff check src tests scripts
ruff format --check src tests scripts   # если используется форматирование
```

Отдельного файла конфигурации ruff в репозитории нет, применяются настройки по умолчанию. В коде встречаются точечные `# noqa` с пояснением причины.

## Автопрогон: scripts/autorun.py

Прогоняет запросы из `testset/cases.json` через контракт `POST /api/v1/programs?mode=auto` и проверяет результат по чек-листам.

```bash
python scripts/autorun.py                          # в процессе через fastapi.testclient.TestClient, без сервера
python scripts/autorun.py --url http://localhost:8000   # против запущенного сервера
python scripts/autorun.py --only 1 3               # только выбранные кейсы
```

Общие проверки для каждого кейса (`_checks`): итоговый объём ровно как в запросе (16, 36, 72, 72, 256 ч для кейсов 1–5), ЛК+ПР+ЛБ+СРС = «Всего» в каждой строке и сумма тем равна модулю, блокирующие проверки 10/10, есть выгрузки `docx` и `json`; далее — проверки, специфичные для кейса (например, для кейса 1 — шаблон ДООП и практика не меньше 8 ч). Результаты: `logs/autorun/<id>.json` и сводка `logs/autorun/summary.md`.

### testset/

`testset/cases.json` — массив из 5 объектов `{id, request, attachments, answers}`: открытые запросы кейса (например, кейс 1 — ДООП «Первые шаги в Python» для 8–9 классов, 16 ч, практика не меньше половины, итоговый тест на 10 вопросов, слайды первых двух занятий). `attachments` и `answers` пусты; формат совпадает с телом `POST /programs`.

## Сквозной регресс

Два прогона против запущенного сервера: API по всем ролям (`scripts/e2e_regression.py`, stdlib + httpx) и интерфейс по ролям в Chromium (`e2e/ui_roles.spec.cjs`, библиотека playwright). Оба печатают `PASS`/`FAIL` по каждой проверке и сводку, при любом `FAIL` код выхода 1.

```bash
cd frontend && npm run build && cd ..                 # интерфейс собирается в frontend/dist, его отдаёт FastAPI
LLM_PROVIDERS=fixtures DATA_DIR=$(mktemp -d) PYTHONPATH=src \
  python -m uvicorn app.main:app --port 8000 &        # детерминированные ответы навыков, чистая БД

python scripts/e2e_regression.py                      # полный цикл по кейсу 4 + админка + автопрогон 5 кейсов (~15 с)
python scripts/e2e_regression.py --case 1             # интерактивный цикл и автопрогон только кейса 1
python scripts/e2e_regression.py --all-cases          # интерактивный цикл по каждому из 5 кейсов
python scripts/e2e_regression.py --base http://host:8000 --skip-autorun

PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers NODE_PATH=$(npm root -g) \
  SHOTS_DIR=/tmp/e2e-shots node e2e/ui_roles.spec.cjs # UI; BASE_URL, CHROMIUM_PATH — по необходимости
```

`e2e_regression.py` проходит: вход всех демо-учёток, `/auth/me`, разделение ролей и анонимный доступ (только автопрогон и чтение); методист — создание в режиме interactive, ответы с «На ваше усмотрение», каркас, перенос часов между темами, перестановка тем (V-21), решения по «!», утверждение каркаса и комплект (асинхронные задания `/jobs`), точечная правка с dry-run, правка часов, версии, сравнение и откат, смена шаблона, адаптация, актуализация, песочница, создание через форму с файлом, назначение экспертов; эксперты timur и olga — только свои модули, комментарии, правка через агента, приём элементов и модуля с оценкой; руководитель — качество, затраты, журнал, возврат с комментарием и утверждение; выгрузки всех семи форматов с проверкой содержимого (python-docx, python-pptx, разбор Moodle XML, поля JSON 4.8, пустые поля `____` в приказе); администратор — пользователи и роли, настройки с маской секрета, параметры навыков, загрузка и поиск в базе знаний, журнал; автопрогон пяти кейсов с чек-листами `scripts/autorun.py`, обязательными НПА (кейс 1 — `law-273`, `order-629`; 2–5 — `law-273`, `order-266`) и асинхронный автопрогон.

`ui_roles.spec.cjs` для каждой роли входит через форму, проверяет стартовую страницу (методист и руководитель — «Программы», эксперт — «Вычитка», администратор — «Администрирование»), открывает основные экраны без ошибок консоли, проверяет перенаправление с запрещённых роли страниц, «Выйти» и `/help`, сохраняет скриншоты в `SHOTS_DIR`. Запускайте его после `e2e_regression.py`: тогда в базе есть программы и задания на вычитку. `npx playwright install` не нужен — используется установленный Chromium.

## Правила для разработчиков

Из `AGENTS.md`:

- Код приложения в `src/app`, запуск `PYTHONPATH=src uvicorn app.main:app`.
- Часы считает только солвер `src/app/solver/hours.py`; модель часы не придумывает.
- Профстандарты, НПА и литература берутся только из `registry/`; то, чего нет в реестре, помечается «не подтверждено».
- Навык — папка `src/app/skills/<имя>/` с `SKILL.md` (frontmatter: name, description, version), `schema_in.json`, `run.py`.
- Секреты только в окружении (`/opt/hackathon/ai.env`, `.env`), в git и логи не попадают.
- Перед коммитом: `pytest -q` и `python scripts/autorun.py`.
- Всё, что запускает CI, одной командой: `make check` (ruff, pytest с порогом покрытия, трассировка SDD, `scripts/export_openapi.py --check`, а в `frontend/` — `npm run check`: ESLint, vitest и сборка). После изменения API обновите схему: `python scripts/export_openapi.py`.

Дополнительно из кода:

- Ошибки API бросаются классами из `src/app/core/errors.py` (`BadRequest`, `Conflict`, `ForbiddenRole`, `Unauthorized`, `NotFound`, `RateLimited`) с русским текстом; формат ответа `{"code", "message_ru", "details"}`.
- Изменяемые во время работы данные пишутся только в `DATA_DIR`: в контейнере файловая система только для чтения.
- Схема БД создаётся `create_all`, миграций нет: не меняйте существующие столбцы без плана переноса данных.
- Доступ к методам — через зависимости `require(...)` и `current_principal` (`src/app/core/security.py`); администратор к программам доступа не имеет.

## Как добавить навык

Навыки находятся по каталогу (`load_skills()` в `src/app/skills/base.py` читает `skills/*/SKILL.md`), поэтому описание навыка подхватывается без регистрации.

1. Создайте `src/app/skills/<имя>/` с пустым `__init__.py`.
2. `SKILL.md`: YAML-frontmatter между `---` и текст инструкции модели. Поля, которые читает `_parse`: `name` (обязательно), `description`, `model_role` (`generate`, `judge`, `rules`, `none`; по умолчанию `generate`), `temperature` (0.2), `max_tokens` (2000), `timeout_s` (60), `retries` (2). Поле `version` выводится в `GET /api/v1/skills`.
3. `schema_in.json` — JSON Schema входа.
4. `run.py` — функция запуска. Существующие навыки (например, `skills/content/run.py`, `skills/classify/run.py`) берут параметры через `skill('<имя>')` и вызывают модель через `get_llm()` из `src/app/llm/client.py`, передавая `CallStats` для учёта токенов; для режима `fixtures` и недоступного шлюза предусмотрите детерминированный ответ.
5. Вызовите навык из оркестратора `src/app/agent/workflow.py` в нужном шаге. Загрузка описания автоматическая, но место вызова в конвейере задаётся кодом.
6. Добавьте тест в `tests/`. После появления навык виден в админке («Навыки агента»): температура, лимит токенов, таймаут, повторы и инструкция переопределяются в `data/runtime/skills_overrides.json`.

## Как добавить акт в реестр

Реестры (`src/app/kb/registry.py`):

- `registry/npa.json` — НПА для нормативной базы программы: `{id, kind, bibl, url, applies: [типы программ], checked_at}`.
- `registry/kb_npa.json` — расширенный реестр актов базы знаний: дополнительно `topics`, `status`, уровни `applies` (включая `vo`, `spo`, `school`) и `core_for` (обязательность для уровня).
- `registry/profstandards.json` — ПС: `{code, title, order, keywords, tf_verified, tf: [{code, title}]}`.
- `registry/literature.json` — `{id, kind, bibl, url, tags, checked_at}`; `registry/tools.json` — `current`, `outdated`, списки сервисов ИИ.

Порядок:

1. Добавьте запись в нужный JSON с актуальной ссылкой на официальный источник и датой `checked_at`. Не добавляйте утратившие силу акты.
2. Если нужна выжимка, создайте `registry/norms/NN-<slug>.md` с YAML-заголовком: `id`, `title`, `source`, `url`, `npa_id` (id записи в реестре), `applies`, `keywords` (основы слов), `checked_at`; в теле — пункты акта с номерами. Непроверенные пункты помечайте «не сверено».
3. Прогоните `pytest -q tests/test_norms.py` (проверяет связь выжимок с реестром и отсутствие отменённых актов).

Администратор может править реестры и без выкладки: `PUT /api/v1/org/registry` пишет раздел в `data/runtime/registry/`, который перекрывает файл из `registry/`.

## Как добавить правило проверки

1. В `src/app/validation/rules.py` напишите функцию `vNN(doc: ProgramDoc, stage: str) -> tuple[status, messages, nodes]`, где `status` — `pass`, `warn`, `fail` или `skip`, `nodes` — id узлов графа для перехода из отчёта. Правило — чистая функция над `ProgramDoc`, без БД.
2. Добавьте `Rule('V-NN', 'Название', check, kind, vNN)` в список `RULES`. `check` — номер блокирующей проверки 1–10 (несколько правил могут относиться к одной проверке) или `None` для предупреждения; `kind` — `code` или `llm`.
3. Если правило должно работать уже на каркасе, добавьте id в `SKELETON_RULES`.
4. При необходимости добавьте починку в `src/app/validation/repair.py` и уточнение судьёй в `src/app/validation/judge.py`.
5. Обновите тексты, где фигурирует число правил («27 правил»): README, `frontend/src/pages/Help.tsx`, описание приложения в `src/app/main.py`, `skills/validate/SKILL.md`. Номера блокирующих проверок и их названия — `CHECK_TITLES` в `validation/rules.py`.

## Как добавить страницу интерфейса

1. Создайте компонент в `frontend/src/pages/<Имя>.tsx`; общие элементы — `frontend/src/components/ui.tsx`, запросы — через функции `frontend/src/api.ts` (они передают токен в `X-MA-Token`).
2. Подключите маршрут в `<Routes>` в `frontend/src/App.tsx`; страницы рабочей области оборачиваются в `<Shell>` (`/app/...`).
3. Добавьте пункт навигации (`NavLink`) в оболочке с учётом роли пользователя (`user.role`).
4. Проверьте сборку: `npm run build` (включает `tsc --noEmit`). Бэкенд отдаёт `index.html` на любой путь вне `/api`, так что новый маршрут работает без изменений на сервере.
5. При появлении пользовательской функции дополните справку `frontend/src/pages/Help.tsx`.
