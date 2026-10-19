# Базовые образы закреплены по digest (индекс multi-arch): повторная сборка берёт те же слои.
# Обновление: docker buildx imagetools inspect node:22-alpine / python:3.12-slim → новый Digest сюда и в docs/deployment.md.

# Сборка интерфейса: npm ci ставит ровно package-lock.json
FROM node:22.23.3-alpine3.24@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Приложение
FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app/src
WORKDIR /app

# Все транзитивные зависимости с точными версиями и sha256 (requirements.lock собран из requirements.txt через uv pip compile)
COPY requirements.lock .
RUN pip install --disable-pip-version-check --require-hashes -r requirements.lock

COPY src ./src
COPY registry ./registry
COPY testset ./testset
COPY scripts ./scripts
COPY --from=ui /ui/dist ./frontend/dist

RUN useradd -m -u 1000 app && mkdir -p /app/data/runtime /app/logs && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
