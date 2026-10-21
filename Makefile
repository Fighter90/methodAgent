# Проверки перед push (ТЗ 4.11, T-26): то же, что CI в .gitea/workflows/ci.yml
PY ?= python3
export PYTHONPATH := src
export LLM_PROVIDERS := fixtures

.PHONY: check lint test trace openapi constraints frontend e2e demo

check: lint test trace openapi constraints frontend

lint:
	ruff check --isolated --select F,E9,I src tests scripts

test:
	$(PY) -m pytest -q --cov=src/app --cov-report=term

trace:
	$(PY) scripts/spec_trace.py

openapi:
	$(PY) scripts/export_openapi.py --check

constraints:
	$(PY) scripts/check_constraints.py

frontend:
	cd frontend && npm ci --no-audit --no-fund && npm run check

# Сквозной регресс по всем ролям на поднятом сервисе: make e2e BASE=http://127.0.0.1:8000
BASE ?= http://127.0.0.1:8000
demo:
	bash scripts/demo.sh

e2e:
	$(PY) scripts/e2e_regression.py --base $(BASE) --all-cases
	BASE_URL=$(BASE) bash scripts/smoke.sh
	$(PY) scripts/demo_clarify_slides.py --base $(BASE)
	BASE_URL=$(BASE) node e2e/ui_roles.spec.cjs  # нужен playwright: NODE_PATH=$$(npm root -g)
