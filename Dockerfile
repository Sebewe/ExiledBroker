# One image for both Railway services (deploy/railway/*.json):
#   web:      uvicorn on $PORT, serving the API (/api) and the built frontend
#   pipeline: eb pipeline run, hourly cron (DuckDB on its volume, publishes to Postgres)

# --- Frontend -----------------------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build
# Compress the build once here, not on every request: the web service sends the .gz
# to browsers that take gzip (api/app.py). Fonts (woff2) are compressed already.
RUN find dist -type f \( -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.svg' \
      -o -name '*.json' \) -size +1k -exec gzip -9 -k {} +

# --- App ----------------------------------------------------------------------------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    EB_WEB_DIST=/app/web/dist EB_DATA_DIR=/app/data \
    EB_API_DOCS=false EB_CORS_ORIGINS='[]'
WORKDIR /app
RUN useradd --create-home app && mkdir -p /app/data && chown app /app/data
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install '.[pg]'
COPY config ./config
COPY --from=web /web/dist ./web/dist
USER app
# The pipeline attaches Postgres through DuckDB's postgres extension: install it at build
# time so a container never downloads it at runtime.
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL postgres')"
EXPOSE 8000
# --limit-concurrency: past 100 open connections uvicorn answers 503 at once instead of
# queueing (the Worker then shows the fallback page), so a flood can't exhaust memory.
CMD ["sh", "-c", "exec uvicorn exiledbroker.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --limit-concurrency 100 --no-server-header"]
