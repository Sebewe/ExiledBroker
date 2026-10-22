# One image for both Railway services:
#   web:    uvicorn on $PORT, serving the API (/api) and the built frontend
#   worker: eb live watch (writes the site's Postgres at EB_DATABASE_URL)

# --- Frontend -----------------------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- App ----------------------------------------------------------------------------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    EB_WEB_DIST=/app/web/dist EB_DATA_DIR=/app/data
WORKDIR /app
RUN useradd --create-home app && mkdir -p /app/data && chown app /app/data
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install '.[pg]'
COPY config ./config
COPY --from=web /web/dist ./web/dist
USER app
# The worker attaches Postgres through DuckDB's postgres extension: install it at build
# time so a container never downloads it at runtime.
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL postgres')"
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn exiledbroker.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
