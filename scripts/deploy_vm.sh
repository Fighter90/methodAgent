#!/usr/bin/env bash
# Развёртывание на ВМ команды: сборка образа и запуск на 0.0.0.0:8000 с автозапуском.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/runtime logs
if [ ! -f .env ] || ! grep -q '^SECRET_KEY=.\+' .env; then
  echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
  chmod 600 .env
fi
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
$DC up -d --build
# Контейнер с restart: unless-stopped поднимается вместе с docker после перезагрузки;
# на случай выключенного docker.service — запись @reboot в crontab.
sudo systemctl enable docker >/dev/null 2>&1 || true
LINE="@reboot cd $(pwd) && $DC up -d >> $(pwd)/logs/reboot.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'metodagent-autostart' ; echo "$LINE # metodagent-autostart" ) | crontab -
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then echo "OK: $(curl -s http://127.0.0.1:8000/health)"; exit 0; fi
  sleep 2
done
echo "Сервис не ответил на /health"; $DC logs --tail 80; exit 1
