#!/usr/bin/env bash
# Демо одной командой (MET-11): поднимает сервер на фикстурах и собирает комплект кейса 1
# через единый эндпоинт POST /api/v1/programs?mode=auto. Код 0 — DEMO PASS.
set -uo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"

( cd frontend && npm run build >/dev/null 2>&1 ) || { echo "FAIL: не собрался интерфейс"; exit 1; }

LLM_PROVIDERS=fixtures DATA_DIR="$(mktemp -d)" PYTHONPATH=src \
  python3 -m uvicorn app.main:app --port "$PORT" >/tmp/demo_server.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT

for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || { echo "FAIL: сервер не поднялся — /tmp/demo_server.log"; exit 1; }
echo "Сервер: http://127.0.0.1:$PORT (LLM_PROVIDERS=fixtures, без сети и ключа)"

python3 scripts/autorun.py --url "http://127.0.0.1:$PORT" --only 1
code=$?
[ "$code" -eq 0 ] && echo "DEMO PASS" || echo "DEMO FAIL"
exit $code
