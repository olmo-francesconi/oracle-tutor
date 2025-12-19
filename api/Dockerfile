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
RUN if [ -f uv.lock ]; then \
      uv sync --active --frozen --no-install-project --extra api; \
    else \
      uv sync --active --no-install-project --extra api; \
    fi

# App source: copy only core and api subpackages
COPY src/oracle_tutor_api/__init__.py ./src/oracle_tutor_api/
COPY src/oracle_tutor_api/core ./src/oracle_tutor_api/core
COPY src/oracle_tutor_api/api ./src/oracle_tutor_api/api


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
COPY --chown=app:app src/oracle_tutor_api/__init__.py ./src/oracle_tutor_api/
COPY --chown=app:app src/oracle_tutor_api/core ./src/oracle_tutor_api/core
COPY --chown=app:app src/oracle_tutor_api/api ./src/oracle_tutor_api/api

EXPOSE 8000

USER app

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; port=os.getenv('PORT','8000'); urllib.request.urlopen('http://127.0.0.1:%s/health'%port).read()" || exit 1

CMD ["sh", "-c", "PORT=\"${PORT:-8000}\"; APP=\"oracle_tutor_api.api.main:app\"; DISABLE_V6_PATH=\"/proc/sys/net/ipv6/conf/all/disable_ipv6\"; BINDV6ONLY_PATH=\"/proc/sys/net/ipv6/bindv6only\"; if [ -f \"$DISABLE_V6_PATH\" ] && [ \"$(cat \"$DISABLE_V6_PATH\" 2>/dev/null || echo 1)\" = \"1\" ]; then exec hypercorn \"$APP\" --bind \"0.0.0.0:${PORT}\"; elif [ -f \"$BINDV6ONLY_PATH\" ] && [ \"$(cat \"$BINDV6ONLY_PATH\" 2>/dev/null || echo 0)\" = \"1\" ]; then exec hypercorn \"$APP\" --bind \"0.0.0.0:${PORT}\" --bind \"[::]:${PORT}\"; else exec hypercorn \"$APP\" --bind \"[::]:${PORT}\"; fi"]


