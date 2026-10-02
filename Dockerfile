# syntax=docker/dockerfile:1

# ---- Build-stage: afhankelijkheden en project installeren in /app/.venv ----
FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81 AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.22@sha256:f513a91fc62fe7c17567eee97230dd198e43edb8a9fbecca843714a4358fe1bc /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Eerst alleen de afhankelijkheden (betere laag-caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Daarna de code
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./
RUN uv sync --locked --no-dev

# ---- Runtime-stage: alleen venv en code, non-root ----
FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81 AS runtime

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=prod \
    FORWARDED_ALLOW_IPS=127.0.0.1

WORKDIR /app

COPY --from=build --chown=root:root /app/.venv /app/.venv
COPY --from=build --chown=root:root /app/app /app/app
COPY --from=build --chown=root:root /app/migrations /app/migrations
COPY --from=build --chown=root:root /app/alembic.ini /app/alembic.ini

USER 10001:10001

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"]

# Trusted proxies via FORWARDED_ALLOW_IPS (standaard alleen localhost; nooit '*')
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
