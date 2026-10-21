---
description: Сквозной регресс всех ролей на локальном сервере с фикстурами (без затрат на модель)
---
1. Подними сервер на свободном порту (например 8765):
   `LLM_PROVIDERS=fixtures DATA_DIR=$(mktemp -d) PYTHONPATH=src nohup python -m uvicorn app.main:app --port 8765 > /tmp/e2e.log 2>&1 &`
   и дождись `curl -fsS http://127.0.0.1:8765/health`.
2. `python scripts/e2e_regression.py --base http://127.0.0.1:8765 --all-cases`
3. `BASE_URL=http://127.0.0.1:8765 bash scripts/smoke.sh`
4. `python scripts/demo_clarify_slides.py --base http://127.0.0.1:8765`
5. Если установлен Playwright: `BASE_URL=http://127.0.0.1:8765 NODE_PATH=$(npm root -g) node e2e/ui_roles.spec.cjs`
6. Останови сервер: `fuser -k 8765/tcp` (не `pkill -f`).

Каждый FAIL разбери до причины и исправь код, потом повтори прогон. Доложи счёт PASS/FAIL. $ARGUMENTS
