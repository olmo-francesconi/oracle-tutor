# Code only: built SPA + app. The model and card data live in the bucket (app/snapshot.py) and are loaded at boot,
# so a data refresh or model change never needs a new image. The same image runs the web service and the
# refresh worker (`python -m app.build --publish`).

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv
WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PATH=/srv/.venv/bin:$PATH
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
COPY app/ app/
COPY --from=web /web/dist static/
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
