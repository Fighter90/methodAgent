# Сборка интерфейса
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Приложение
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app/src
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

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
