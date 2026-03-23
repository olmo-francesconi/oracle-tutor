# Project: Oracle Tutor (mtg-search)

## Purpose
Fast, fuzzy-search engine for Magic: The Gathering cards — TF-IDF semantic search over Scryfall bulk data with EDHREC ranking, serving a React SPA via a FastAPI backend.

## Tech stack
- **Backend:** Python 3.12+, FastAPI, Hypercorn, SQLAlchemy 2, PostgreSQL (pgvector), scikit-learn (TF-IDF), uv
- **Frontend:** React 19, TypeScript 5.9, Vite, TailwindCSS 4, Tanstack Query, Framer Motion
- **Infra:** Docker Compose (local), Railway (production), GitHub Actions (CI)

## Repo structure
```
api/                    FastAPI service + Pytest suite
  src/oracle_tutor_api/ Main package
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
- `ORACLE_TUTOR_API_WORKER_TOKEN` — shared secret for internal rebuild endpoint
- `ORACLE_TUTOR_API_CORS_ORIGINS` — comma-separated allowed origins
- `ORACLE_TUTOR_API_TFIDF_REBUILD_IN_SUBPROCESS` — set `1` to reclaim memory after TF-IDF build
- `VITE_API_URL` — frontend API base (default `/api`)

## Project-specific rules
- Version is kept in sync between `api/pyproject.toml` and `frontend/package.json`
- Worker is a one-shot container; it runs daily on Railway Cron and exits after ingestion
- Never set `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET=true` in production without explicit intent
- TF-IDF matrix is built in-memory on startup; avoid blocking the event loop during rebuild

---

## Project files

- [ARCHITECTURE.md](../ARCHITECTURE.md) — system design, components, key decisions
- [ROADMAP.md](../ROADMAP.md) — long-term goals and milestones
- [TODO.md](../TODO.md) — short-term goals and current focus
