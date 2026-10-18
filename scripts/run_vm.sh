#!/usr/bin/env bash
# Запуск без Docker (NFR-15, ТЗ 4.11): виртуальное окружение Python, SQLite в data/,
# встроенная очередь заданий, статика SPA отдаётся самим FastAPI на порту 8000,
# автозапуск после перезагрузки — запись @reboot в crontab.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
mkdir -p data/runtime logs
if [ ! -f .env ] || ! grep -q '^SECRET_KEY=.\+' .env; then
  echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
  chmod 600 .env
fi
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    (cd frontend && npm ci --silent && npm run build --silent)
  else
    echo "Нет npm и собранного frontend/dist: API заработает, интерфейс — после сборки фронтенда"
  fi
fi
# Ключ шлюза LLM на ВМ хакатона лежит вне репозитория; переменные читаются в окружение, в журнал не пишутся
set -a
. ./.env
if [ -r /opt/hackathon/ai.env ]; then . /opt/hackathon/ai.env; fi
set +a
pkill -f "uvicorn app.main:app --host 0.0.0.0 --port 8000" 2>/dev/null || true
PYTHONPATH="$ROOT/src" DATA_DIR="$ROOT/data/runtime" nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips '*' >> logs/app.log 2>&1 &
LINE="@reboot cd $ROOT && bash scripts/run_vm.sh >> $ROOT/logs/reboot.log 2>&1"
{ crontab -l 2>/dev/null | grep -v 'metodagent-autostart' || true; echo "$LINE # metodagent-autostart"; } | crontab -
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then echo "OK: $(curl -s http://127.0.0.1:8000/health)"; exit 0; fi
  sleep 2
done
echo "Сервис не ответил на /health"; tail -n 80 logs/app.log; exit 1
