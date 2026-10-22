#!/usr/bin/env bash
# Развёртывание на ВМ команды: сборка образа и запуск на 0.0.0.0:8000 с автозапуском.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/runtime logs
if [ ! -f .env ] || ! grep -q '^SECRET_KEY=.\+' .env; then
  echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
  chmod 600 .env
fi
# Ключ шлюза Cloud.ru: из файла хакатона берутся только ключ и адрес, под именами приложения
AI_ENV=/opt/hackathon/ai.env
if [ -r "$AI_ENV" ]; then
  grep -vE '^LLM_(API_KEY|BASE_URL)=' .env > .env.tmp || true
  sed -nE 's/^(export +)?[A-Z_]*API_KEY=/LLM_API_KEY=/p; s/^(export +)?[A-Z_]*BASE_URL=/LLM_BASE_URL=/p' "$AI_ENV" >> .env.tmp
  mv .env.tmp .env && chmod 600 .env
fi
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
$DC up -d --build
# Контейнер с restart: unless-stopped поднимается вместе с docker после перезагрузки;
# на случай выключенного docker.service — запись @reboot в crontab.
sudo systemctl enable docker >/dev/null 2>&1 || true
LINE="@reboot cd $(pwd) && $DC up -d >> $(pwd)/logs/reboot.log 2>&1"
{ crontab -l 2>/dev/null | grep -v 'metodagent-autostart' || true; echo "$LINE # metodagent-autostart"; } | crontab -
# Ждём готовности тихо: пока контейнер стартует, соединение сбрасывается — это не ошибка
for i in $(seq 1 45); do
  if body=$(curl -fs --max-time 3 http://127.0.0.1:8000/health 2>/dev/null); then echo "OK: $body"; exit 0; fi
  sleep 2
done
echo "Сервис не ответил на /health"; $DC logs --tail 80; exit 1
