#!/usr/bin/env bash
# Локальный запуск без Docker и без make: окружение из lock-файла, сборка интерфейса, uvicorn на переднем плане.
#   bash scripts/run_local.sh                 # порт 8000, режим fixtures (без сети), если LLM_API_KEY не задан
#   PORT=8765 bash scripts/run_local.sh       # другой порт
#   LLM_API_KEY=... LLM_BASE_URL=... bash scripts/run_local.sh   # генерация моделью Cloud.ru
# Нужны Python 3.12 и Node 22 (npm). Переменные: PORT, HOST, VENV, DATA_DIR, PYTHON, SKIP_UI=1.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
VENV="${VENV:-$ROOT/.venv}"
export DATA_DIR="${DATA_DIR:-$ROOT/data/runtime}"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.12 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))'; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || { echo "Нужен Python 3.12 (python3.12 не найден; укажите PYTHON=/путь/к/python3.12)"; exit 1; }

# 1. Окружение Python строго по requirements.lock (точные версии и хэши всех транзитивных пакетов)
if [ ! -x "$VENV/bin/python" ]; then
  echo "== Создаю окружение $VENV ($("$PY" -V))"
  "$PY" -m venv "$VENV"
fi
if [ ! -f "$VENV/.lock.sha" ] || ! sha256sum -c --status "$VENV/.lock.sha" 2>/dev/null; then
  echo "== Ставлю зависимости из requirements.lock (--require-hashes)"
  "$VENV/bin/python" -m pip install -q --disable-pip-version-check --require-hashes -r requirements.lock
  sha256sum requirements.lock > "$VENV/.lock.sha"
fi

# 2. Интерфейс: npm ci ставит ровно то, что в package-lock.json
if [ "${SKIP_UI:-0}" != 1 ] && [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "== Собираю интерфейс (Node $(node -v)): npm ci && npm run build"
    (cd frontend && npm ci --no-audit --no-fund --silent && npm run build --silent)
  else
    echo "!! npm не найден: заработает только API (/docs), интерфейс — после сборки frontend"
  fi
fi

# 3. Режим генерации: без ключа — fixtures (детерминированная резервная генерация, сеть не нужна)
#    Ключ берётся из окружения или из .env (его читает и само приложение); значение не печатается.
if [ -n "${LLM_API_KEY:-}" ] || grep -qE '^(LLM|CLOUDRU)_API_KEY=.+' .env 2>/dev/null; then
  export LLM_PROVIDERS="${LLM_PROVIDERS:-cloudru}"
else
  export LLM_PROVIDERS="${LLM_PROVIDERS:-fixtures}"
fi
mkdir -p "$DATA_DIR" logs
echo "== Режим LLM_PROVIDERS=$LLM_PROVIDERS, данные: $DATA_DIR"
echo "== Открыть: http://$HOST:$PORT  (вход madina / demo), API: http://$HOST:$PORT/docs"
exec env PYTHONPATH="$ROOT/src" "$VENV/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT"
