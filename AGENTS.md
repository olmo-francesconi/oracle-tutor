# Repository Guidelines

## Project Structure & Module Organization

This repository is split into two apps:

- `backend/`: FastAPI service, Alembic migrations, ingestion jobs, and tests.
- `frontend/`: React 19 + TypeScript SPA built with Vite.

Backend code lives in `backend/src/ot_backend/` under `api/`, `core/`, `ingest/`, and `embed/`. Backend tests live in `backend/tests/`. Frontend code lives in `frontend/src/`, with reusable UI in `components/`, route pages in `pages/`, and helpers in `lib/`. Static assets live in `frontend/public/`.

## Build, Test, and Development Commands

Run the full stack from the repo root with `docker compose up --build`.

Backend:
- `cd backend && uv sync --all-extras --group dev`: install Python dependencies.
- `cd backend && uv run hypercorn ot_backend.api.main:app --reload --bind 0.0.0.0:8000`: run the API locally.
- `cd backend && uv run ruff check src/ --fix`: lint and auto-fix Python code.
- `cd backend && uv run basedpyright src/`: run static type checks.
- `cd backend && uv run pytest -x -q`: run tests.

Frontend:
- `cd frontend && npm install`: install dependencies.
- `cd frontend && npm run dev`: start the Vite dev server.
- `cd frontend && npm run lint`: run ESLint.
- `cd frontend && npm run build`: type-check and build production assets.

## Coding Style & Naming Conventions

Prefer explicit, readable code over compact tricks. Avoid magic numbers; name important constants. Python targets 3.12+, uses Ruff, and keeps lines within 120 chars. TypeScript uses 2-space indentation, no semicolons, single quotes, trailing commas where valid, and Tailwind sorting through Prettier. Use `PascalCase` for React components, `camelCase` for functions and variables, and `snake_case` for Python modules and tests.

## Testing Guidelines

Backend tests use `pytest`; place new tests in `backend/tests/` as `test_*.py`. Write tests for new logic and prefer integration-style coverage over heavy mocking. The frontend currently has no committed test suite, so at minimum run `npm run lint` and `npm run build` before a PR.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit prefixes such as `fix:`, `refactor:`, `docs:`, and `chore:`. Keep commit subjects imperative and concise, for example `fix: handle empty oracle query`. PRs should stay focused on one concern, explain the user-visible change, link related issues, and include screenshots for frontend changes.
