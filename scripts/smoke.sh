#!/usr/bin/env bash
# Дымовая проверка запущенного сервиса по основному сценарию:
#   /health → вход madina/demo → автопрогон одного кейса testset → статус и проверки → все ссылки выгрузки отдают 200.
#   bash scripts/smoke.sh                              # http://127.0.0.1:8000, кейс 1
#   BASE_URL=http://127.0.0.1:8765 CASE=3 bash scripts/smoke.sh
# Нужны curl и python3 (только стандартная библиотека). Код выхода 0 — всё прошло.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE="${BASE_URL:-http://127.0.0.1:8000}"
CASE="${CASE:-1}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PY="${PYTHON:-python3}"

fail() { echo "FAIL: $*"; exit 1; }
json() { "$PY" -c "import json,sys; d=json.load(open('$1')); print($2)"; }

echo "1) GET $BASE/health"
curl -fsS "$BASE/health" -o "$TMP/health.json" || fail "сервис не отвечает на $BASE/health"
echo "   $(cat "$TMP/health.json")"
[ "$(json "$TMP/health.json" "d['status']")" = ok ] || fail "status != ok"

echo "2) POST /api/v1/auth/login (madina / demo)"
code=$(curl -sS -o "$TMP/login.json" -w '%{http_code}' -H 'Content-Type: application/json' \
  -d '{"login":"madina","password":"demo"}' "$BASE/api/v1/auth/login")
[ "$code" = 200 ] || fail "вход: HTTP $code"
TOKEN="$(json "$TMP/login.json" "d.get('access_token') or d.get('token')")"
[ -n "$TOKEN" ] && [ "$TOKEN" != None ] || fail "в ответе входа нет токена"
echo "   роль: $(json "$TMP/login.json" "d.get('role') or d.get('user',{}).get('role','?')"), токен получен"

echo "3) POST /api/v1/programs?mode=auto — кейс $CASE из testset/cases.json"
"$PY" - "$CASE" > "$TMP/req.json" <<'EOF'
import base64, json, sys
from pathlib import Path
case = next(c for c in json.loads(Path('testset/cases.json').read_text()) if c['id'] == int(sys.argv[1]))
atts = [{'name': Path(a).name, 'content_base64': base64.b64encode(Path(a).read_bytes()).decode()} for a in case['attachments']]
print(json.dumps({'request': case['request'], 'attachments': atts, 'answers': case['answers']}, ensure_ascii=False))
EOF
t0=$(date +%s)
code=$(curl -sS -o "$TMP/run.json" -w '%{http_code}' --max-time 1800 -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" --data-binary @"$TMP/req.json" "$BASE/api/v1/programs?mode=auto")
[ "$code" = 200 ] || { head -c 600 "$TMP/run.json"; echo; fail "автопрогон: HTTP $code"; }
"$PY" - "$TMP/run.json" "$(( $(date +%s) - t0 ))" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
sk, rep = r['skeleton'], r['report']
print(f"   id={r.get('id') or r.get('program_id')} status={r['status']} за {sys.argv[2]} с")
print(f"   «{sk['title']}», тип {sk['type']}, {sk['totals']['all']} ч, модулей {len(sk['modules'])}")
print(f"   блокирующие проверки {rep['blocking_checks']}, правил пройдено {rep['rules_passed']}/{rep['rules_total']}")
print(f"   токены {r['tokens']['in']}+{r['tokens']['out']}, {r['tokens']['cost_rub']} ₽; выгрузки: {', '.join(r['files'])}")
bad = []
if r['status'] in ('error', 'failed'):
    bad.append(f"status={r['status']}")
done, total = rep['blocking_checks'].split('/')
if done != total:
    bad.append(f"блокирующие {rep['blocking_checks']}")
if not {'docx', 'json'} <= set(r['files']):
    bad.append('нет ссылок docx/json')
if bad:
    sys.exit('FAIL: ' + '; '.join(bad))
EOF

echo "4) Ссылки выгрузки (GET с токеном, ожидается 200)"
"$PY" -c "import json; [print(k, v) for k, v in json.load(open('$TMP/run.json'))['files'].items()]" > "$TMP/files.txt"
while read -r fmt url; do
  # Ссылка строится от адреса запроса; при обращении через прокси заменяем хост на BASE
  path="/api/v1/${url#*/api/v1/}"
  code=$(curl -sS -o "$TMP/out.$fmt" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$BASE$path")
  size=$(wc -c < "$TMP/out.$fmt")
  printf '   %-14s HTTP %s  %8s байт\n' "$fmt" "$code" "$size"
  [ "$code" = 200 ] && [ "$size" -gt 0 ] || fail "выгрузка $fmt: HTTP $code"
done < "$TMP/files.txt"

echo "OK: основной сценарий пройден"
