# Project: Oracle Tutor (mtg-search)

## Purpose
Fast, semantic search engine for Magic: The Gathering cards — pgvector embeddings with ONNX Runtime inference over Scryfall bulk data, serving a React SPA via a FastAPI backend.

## Tech stack
- **Backend:** Python 3.12+, FastAPI, Hypercorn, SQLAlchemy 2, PostgreSQL (pgvector), ONNX Runtime (inference), sentence-transformers (training only), uv
- **Frontend:** React 19, TypeScript 5.9, Vite 7, TailwindCSS 4, TanStack Query, Framer Motion, React Router 7
- **Infra:** Docker Compose (local), Railway (production), GitHub Actions (CI)

## Repo structure
```
backend/                FastAPI service + Pytest suite
  src/ot_backend/
    api/                Route handlers + Pydantic response schemas
    core/               Config, DB engine/session, schema init, ORM models, logging
    embed/              ONNX inference, model training, embedding computation
    ingest/             One-shot Scryfall ingestion and Tagger sync
  tests/                Pytest suite (SQLite in-memory)
  Dockerfile            API image
  Dockerfile.worker     Ingest worker image
  Dockerfile.semantic-worker  Training + embedding worker image
frontend/               React + Vite SPA
  src/
    components/         UI components (grid, filters, overlays, mobile)
    pages/              OracleSearchPage, CardPage
    lib/                Small helpers (cn, seo)
  nginx/                Nginx config/template for production
  Dockerfile            Multi-stage build (Vite dev + nginx runtime)
.github/workflows/      ci.yml (frontend + workers), api-ci.yml (pytest + API build)
docker-compose.yml      Local dev: db + api + worker-ingest + worker-embed + frontend
```

## Branch conventions
- `main` — production releases (protected)
- `develop` — active development, PRs merge here first
- `production` — alternative production channel
- Feature branches: `feat/<name>`, fixes: `fix/<name>`

## Key environment variables
- `DATABASE_URL` — required in production (Railway injects)
- `ORACLE_TUTOR_API_ENV` — `development` | `production`
- `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET` — `true` only for local reset workflows
- `VITE_API_URL` — frontend API base (default `/api`)
- `SEMANTIC_MODEL_PATH` — directory containing ONNX model (`onnx/model.onnx`) used for inference

## Local dev

```bash
docker compose up --build   # starts db + api + frontend (workers are one-shot)
```

## Python dev workflow (run in `backend/` directory)

Before committing or running tests, always run in this order:

```bash
# 1. Lint + auto-fix imports/style
uv run ruff check src/ --fix

# 2. Type check (0 errors expected)
uv run basedpyright

# 3. Tests
uv run pytest tests/ -x -q
```

Notes:
- `uv sync --all-extras --group test` is required once to populate the venv
- basedpyright must be run from `backend/` (where `pyrightconfig.json` lives) to pick up the venv
- Ruff config is in `pyproject.toml` under `[tool.ruff]` — line length 120, E/F/I rules
- ~720 basedpyright warnings are expected noise (`reportAny` from argparse/dynamic imports); only errors matter

## Frontend dev workflow (run in `frontend/` directory)

```bash
npm install        # first time only
npm run dev        # dev server at localhost:5173 (proxies /api to backend)
npm run lint       # ESLint
npm run build      # production build
```

---

## Project-specific rules
- Version is kept in sync between `backend/pyproject.toml` and `frontend/package.json`
- Worker is a one-shot container; it runs daily on Railway Cron and exits after ingestion
- Never set `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET=true` in production without explicit intent

---

## Project files

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design, components, key decisions
- [ROADMAP.md](ROADMAP.md) — long-term goals and milestones
- [TODO.md](TODO.md) — short-term goals and current focus
