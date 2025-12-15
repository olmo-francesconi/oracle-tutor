# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.5.7 AS uv

# ---- Builder: install deps into a venv with uv (fast), compile extensions, etc.
FROM python:3.11-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=uv /uv /usr/local/bin/uv

# build-essential and libpq-dev are often needed for python packages (and psycopg builds)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"

# Copy dependency manifest(s) first for better layer caching
COPY requirements.txt ./

# Install PyTorch CPU-only wheels FIRST to avoid downloading the massive CUDA builds.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install -r requirements.txt

# Copy application code
COPY pyproject.toml ./
COPY src/ ./src/
COPY tests/ ./tests/

# Editable install keeps docker-compose volume mounts + uvicorn --reload working.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install -e .

# ---- Runtime: minimal image with just venv + app
FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Runtime-only libs (no compiler toolchain)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

RUN mkdir -p data

EXPOSE 8000

CMD ["uvicorn", "oracle_tutor_api.api:app", "--host", "0.0.0.0", "--port", "8000"]
