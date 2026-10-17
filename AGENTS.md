# Правила для агентов, работающих с репозиторием

- Код приложения в `src/app`, запуск `PYTHONPATH=src uvicorn app.main:app`.
- Часы считает только солвер `src/app/solver/hours.py`; модель часы не придумывает.
- Профстандарты, НПА и литература берутся только из `registry/`; то, чего нет в реестре, помечается «не подтверждено».
- Навык = папка `src/app/skills/<имя>/` с `SKILL.md` (frontmatter: name, description, version), `schema_in.json`, `run.py`.
- Секреты только в окружении (`/opt/hackathon/ai.env`, `.env`), в git и логи не попадают.
- Перед коммитом: `pytest -q` и `python scripts/autorun.py`.
