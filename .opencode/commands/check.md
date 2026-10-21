---
description: Все проверки перед коммитом (линтер, тесты с покрытием, трассировка, OpenAPI, схемы навыков, фронтенд)
---
Прогони проверки из корня репозитория и исправь всё, что упало:

1. `ruff check --isolated --select F,E9,I src tests scripts`
2. `PYTHONPATH=src LLM_PROVIDERS=fixtures python -m pytest -q --cov=src/app` (порог покрытия 70 %)
3. `PYTHONPATH=src python scripts/spec_trace.py --markdown`; если таблица изменилась, вставь её в `specs/README.md` между `<!-- trace:begin -->` и `<!-- trace:end -->`
4. `DATA_DIR=$(mktemp -d) PYTHONPATH=src python scripts/export_openapi.py --check` (при расхождении запусти без `--check` и закоммить `docs/openapi.json`)
5. `PYTHONPATH=src python scripts/export_skill_schemas.py --check`
6. `cd frontend && npm run check`

Коротко доложи итог: сколько тестов, покрытие, что исправил. $ARGUMENTS
