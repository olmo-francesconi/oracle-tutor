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
  CMD python -c "import os,urllib.request; port=os.getenv('PORT','8000'); urls=[f'http://127.0.0.1:{port}/health', f'http://[::1]:{port}/health']; last=None\nfor u in urls:\n  try:\n    urllib.request.urlopen(u, timeout=2).read(); raise SystemExit(0)\n  except Exception as e:\n    last=e\nraise SystemExit(1)" || exit 1

# Bind to IPv6 any-address. On Linux this is typically dual-stack (accepts IPv4-mapped too),
# which avoids intermittent failures when upstream resolves to an IPv6 address.
CMD ["sh", "-c", "uvicorn oracle_tutor_api.main:app --host :: --port ${PORT:-8000}"]


