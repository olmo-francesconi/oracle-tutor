# Repository Guidelines

## Project Structure & Module Organization

This repository is split into two active apps:

- `backend/`: FastAPI service, Alembic migrations (single `0001_initial_schema.py`), ingestion + semantic workers, and tests.
- `frontend/`: React 19 + TypeScript SPA built with Vite, using TanStack Query v5 for server state and zod for response validation.

Backend code lives in `backend/src/ot_backend/` under `api/`, `core/`, `ingest/`, and `semantic/`. The `semantic/` package contains ONNX inference (`index.py`), the model registry and promotion logic (`model_registry.py`, `model_promotion.py`, `artifacts.py`, `bundle_registration.py`), the one-shot workers (`dataset_worker.py`, `train_worker.py`, `promote_worker.py`), and the DB-backed job queue (`semantic_jobs.py`). Backend tests live in `backend/tests/` and run against a real Postgres via testcontainers. Frontend code lives in `frontend/src/`, with reusable UI in `components/`, public search in `public/`, admin panel in `admin/`, and helpers in `lib/`. Frontend tests live under `frontend/src/`. The pre-promotion SPA is archived in `frontend-legacy/` and should only be touched for rollback or reference work.

## Build, Test, and Development Commands

Run the full local stack from the repo root with `docker compose up --build` (starts db + minio + api + frontend).

Backend:
- `cd backend && uv sync --all-extras --group dev`: install Python dependencies (includes testcontainers).
- `cd backend && uv run hypercorn ot_backend.api.main:app --reload --bind 0.0.0.0:8000`: run the API locally.
- `cd backend && uv run ruff check src/ --fix`: lint and auto-fix Python code.
- `cd backend && uv run basedpyright src/`: run static type checks.
- `cd backend && uv run pytest -x -q`: run tests (requires Docker; spawns a pgvector container per session).

Frontend:
- `cd frontend && npm install`: install dependencies.
- `cd frontend && npm run dev`: start the Vite dev server.
- `cd frontend && npm run lint`: run ESLint.
- `cd frontend && npm run test`: run Vitest.
- `cd frontend && npm run build`: type-check and build production assets.

## Coding Style & Naming Conventions

Prefer explicit, readable code over compact tricks. Avoid magic numbers; name important constants. Python targets 3.12+, uses Ruff, and keeps lines within 120 chars. TypeScript uses 2-space indentation, no semicolons, single quotes, trailing commas where valid, and Tailwind sorting through Prettier. Use `PascalCase` for React components, `camelCase` for functions and variables, and `snake_case` for Python modules and tests.

Postgres is the only supported database. Do not add dialect branching (`if dialect == "postgresql"`); tests run against real Postgres via testcontainers. The ORM models in `backend/src/ot_backend/core/models.py` are the source of truth for the schema.

## Testing Guidelines

Backend tests use `pytest`; place new tests in `backend/tests/` as `test_*.py`. Write tests for new logic and prefer integration-style coverage over heavy mocking. The test harness runs a `pgvector/pgvector:pg17` container once per session and seeds fresh data per test. Frontend tests use Vitest with a per-test `QueryClientProvider` from `src/lib/testQueryClient.tsx`. Run `npm run lint`, `npm run test`, and `npm run build` before a PR.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit prefixes such as `fix:`, `refactor:`, `docs:`, and `chore:`. Keep commit subjects imperative and concise, for example `fix: handle empty oracle query`. Never add `Co-Authored-By` or any other trailer. PRs should stay focused on one concern, explain the user-visible change, link related issues, and include screenshots for frontend changes.
