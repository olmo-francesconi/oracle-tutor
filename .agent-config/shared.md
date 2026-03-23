# Project: Oracle Tutor (mtg-search)

## Purpose
Fast, fuzzy-search engine for Magic: The Gathering cards — semantic vector search over Scryfall bulk data using sentence-transformers and pgvector, serving a React SPA via a FastAPI backend.

## Tech stack
- **Backend:** Python 3.12+, FastAPI, Hypercorn, SQLAlchemy 2, PostgreSQL (pgvector), sentence-transformers, uv
- **Frontend:** React 19, TypeScript 5.9, Vite, TailwindCSS 4, Tanstack Query, Framer Motion
- **Infra:** Docker Compose (local), Railway (production), GitHub Actions (CI)

## Repo structure
```
backend/                FastAPI service + Pytest suite
  src/ot_backend/       Main package
  tests/                Pytest tests
  Dockerfile            API image
  Dockerfile.worker     One-shot data ingestion worker image
frontend/               React + Vite SPA
  src/                  Components, pages, API client
  Dockerfile            Multi-stage build (nginx)
.github/workflows/      ci.yml (frontend), api-ci.yml (pytest)
docker-compose.yml      Local dev: db + api + worker + frontend
docker-compose.prod.yml Production overrides
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
- `SEMANTIC_MODEL_PATH` — directory containing a trained sentence-transformers model

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
- 720 basedpyright warnings are expected noise (`reportAny` from argparse/dynamic imports); only errors matter

---

## Project-specific rules
- Version is kept in sync between `backend/pyproject.toml` and `frontend/package.json`
- Worker is a one-shot container; it runs daily on Railway Cron and exits after ingestion
- Never set `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET=true` in production without explicit intent

---

## Project files

- [ARCHITECTURE.md](../ARCHITECTURE.md) — system design, components, key decisions
- [ROADMAP.md](../ROADMAP.md) — long-term goals and milestones
- [TODO.md](../TODO.md) — short-term goals and current focus
