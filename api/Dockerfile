# syntax=docker/dockerfile:1

##
# Multi-stage build:
# - builder uses uv to create a venv with dependencies
# - runtime copies the venv + source only
##

FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS builder

WORKDIR /app

# Copy dependency metadata first to maximize Docker layer caching.
COPY pyproject.toml uv.lock* ./

RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV UV_CACHE_DIR=/root/.cache/uv

# If uv.lock is present, use a frozen install; otherwise resolve from pyproject.toml.
RUN if [ -f uv.lock ]; then uv sync --active --frozen --no-install-project; else uv sync --active --no-install-project; fi

# App source (kept separate from deps for cache-friendliness).
COPY src ./src


FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    PORT=8000

RUN set -eux; \
    groupadd -r app && useradd -r -g app -d /app -s /usr/sbin/nologin app; \
    mkdir -p /app/data; \
    chown -R app:app /app/data

COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app src ./src

EXPOSE 8000

USER app

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; port=os.getenv('PORT','8000'); urllib.request.urlopen('http://127.0.0.1:%s/health'%port).read()" || exit 1

# Railway may route traffic over both IPv4 and IPv6. Uvicorn does NOT provide dual-stack
# binding automatically when listening on `::`, so we start two listeners:
# - IPv4: 0.0.0.0:$PORT (foreground)
# - IPv6: ::      :$PORT (best-effort background; logs warning if unavailable)
CMD ["sh", "-c", "port=${PORT:-8000}; (uvicorn oracle_tutor_api.main:app --host :: --port \"$port\" 2>&1 || echo \"[warn] IPv6 bind failed; continuing with IPv4 only\" >&2) & exec uvicorn oracle_tutor_api.main:app --host 0.0.0.0 --port \"$port\""]


