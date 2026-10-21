# Правила для агентов, работающих с репозиторием

МетодАгент — ИИ-методист для АЦР: бэкенд FastAPI (`src/app`), фронтенд React (`frontend/`), спецификации SDD (`specs/`), документация (`docs/`, `wiki/`). Отвечай пользователю по-русски, коротко, с доказательствами (`файл:строка`, вывод команды).

## Как работать
- Делай задачу до конца без лишних вопросов: правка → проверки → коммит → push → деплой → проверка стенда. Спрашивай только о том, что нельзя отменить.
- Перед коммитом всегда `/check` (или `make check`); после изменения логики — `/e2e`.
- Сверяйся с ТЗ: `docs/tz-compliance.md`, `specs/*.md`. Новое поведение = новое требование `SPEC-<MODULE>-NN` в EARS-форме в `specs/` + тест, docstring которого начинается с этого ID; затем обнови таблицу трассировки (`scripts/spec_trace.py --markdown` → `specs/README.md` между `<!-- trace:begin -->` и `<!-- trace:end -->`).
- Каждая версия: запись в `docs/changelog.md` и `wiki/История-изменений.md`; при изменении API — `docs/openapi.json` (`scripts/export_openapi.py`), при изменении навыков — `scripts/export_skill_schemas.py`.

## Код
- Запуск: `PYTHONPATH=src uvicorn app.main:app`; без модели — `LLM_PROVIDERS=fixtures`.
- Часы считает только солвер `src/app/solver/hours.py`; модель часы не придумывает.
- Профстандарты, НПА и литература берутся только из `registry/`; то, чего нет в реестре, помечается «не подтверждено».
- Навык = папка `src/app/skills/<имя>/` с `SKILL.md` (frontmatter: name, description, version), `schema_in.json`, `schema_out.json`, `run.py`.
- Модель только Cloud.ru через собственный клиент `src/app/llm/gateway.py` (httpx). Не добавлять SDK других провайдеров и их переменные окружения — жюри снимает за это баллы, тест проверяет `requirements.txt`.
- Бюджет модели около 100 ₽ в сутки: локальные тесты и e2e — только на фикстурах; живые прогоны на стенде — точечно.
- Тесты не отключать, не помечать skip, порог покрытия 70 %.

## Git и авторство
- Коммиты только от автора, без строк `Co-Authored-By`, без упоминаний ИИ и агентов:
  `git -c user.name="Емельянов Сергей Борисович" -c user.email="sbemelyanov@edu.hse.ru" commit -m "…"`
- Сообщения коммитов по-русски, о том, что изменилось.
- Push только в `origin main` выданного репозитория Gitea (`git.hub.gigaschool.ru/tochka-sborki-2026-team-098/project`), без `--force`. С 06:00 до 10:00 МСК push закрыт (проверка жюри берёт последний коммит main). Дедлайн — 23.10.

## Стенд
- Стенд: https://tochka-sborki-2026-team-098.hub.gigaschool.ru (methodagent.ru перенаправляет туда), проверка — `/health`.
- Деплой: `ssh -J jump@84.54.59.198 tochka-sborki-2026-team-098@10.250.0.101 'cd ~/project && git pull --ff-only origin main && ./scripts/deploy_vm.sh'`.
- e2e на ВМ запускать внутри контейнера (на хосте нет python-docx/pptx): `docker compose exec -T app python scripts/e2e_regression.py --base http://127.0.0.1:8000`.

## Секреты
- Секреты только в окружении: ключ модели в `/opt/hackathon/ai.env` на ВМ, `.env` (не в git), пароли jump/ВМ в `~/.tochka.env` на Mac.
- Никогда не печатать, не вводить за пользователя и не сохранять пароли, токены и ключи в файлы, коммиты, логи и чат. Если ssh или git просит пароль — попроси пользователя ввести его самому.

## Mac
- Если на Mac кончается место на диске, запусти из домашней папки `~/mac_cleanup.sh`.
