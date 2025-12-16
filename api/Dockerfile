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
    PYTHONPATH=/app/src

COPY --from=builder /opt/venv /opt/venv
COPY src ./src

EXPOSE 8000

CMD ["uvicorn", "oracle_tutor_api.main:app", "--host", "0.0.0.0", "--port", "8000"]


