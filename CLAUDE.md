# Oracle Tutor (mtg-search)

Fast, semantic search engine for Magic: The Gathering cards — pgvector embeddings with ONNX Runtime inference over Scryfall bulk data, serving a React SPA via a FastAPI backend.

## Tech stack

- **Backend:** Python 3.12+, FastAPI 0.115+, Hypercorn 0.17+, SQLAlchemy 2, psycopg 3.2+, pgvector 0.3+, ONNX Runtime 1.20+, Alembic 1.14+, sentence-transformers 3.0+ (training only), uv
- **Frontend:** React 19.2, TypeScript 5.9, Vite 7.2, TailwindCSS 4.1, TanStack Query 5.90, TanStack Virtual 3.13, React Router 7.9, Framer Motion 12.23, Axios 1.13, Phosphor Icons 2.1
- **Infra:** Docker Compose (local), Railway (production), GitHub Actions (CI)

## Repo structure

```
backend/                FastAPI service + Pytest suite
  src/ot_backend/
    api/                Route handlers (main.py) + Pydantic response schemas (schemas.py)
    core/               Config, DB engine/session, schema init, ORM models, logging
    embed/              ONNX inference (index.py), model training + export (pipeline.py)
    ingest/             One-shot Scryfall ingestion (data_builder.py) and Tagger sync
  tests/                Pytest suite (SQLite in-memory)
  alembic/              DB migrations (versions/0001_initial_schema.py)
  scripts/              Local utility/profiling scripts
  Dockerfile            API image
  Dockerfile.scryfall-sync    Scryfall ingest image
frontend/               React + Vite SPA
  src/
    app/                Search shell and route-level orchestration
    components/         UI components, overlays, and shared presentation
    lib/                API client, filters, URL state, and helpers
    test/               Vitest setup helpers
  nginx/                Nginx config/template for production
  Dockerfile            Multi-stage build (Vite dev + nginx runtime)
.github/workflows/      ci.yml (frontend), api-ci.yml (backend)
docker-compose.yml      Local dev: db + api + scryfall-sync + frontend
```

## Architecture

### Data model (3-layer)
- `cards_raw` — all Scryfall printings (~300k rows), PK = Scryfall UUID
- `cards` — oracle-deduplicated, PK = `oracle_id` (~30k rows)
- `card_faces` — composite PK `(oracle_id, face_ix)`
- `card_face_semantic_embeddings` — composite PK `(oracle_id, face_ix)`, 384-dim pgvector

Additional tables: `tags`, `card_taggings`, `tag_ancestor_map`, `card_relationships`, `system_metadata`, `ingestion_logs`

Semantic model registry tables: `semantic_models`, `semantic_model_artifacts`, `semantic_model_embeddings`, `semantic_jobs`
Note: `card_face_semantic_embeddings` still exists for uniqueness scoring; live search embeddings are in `semantic_model_embeddings`.

### Semantic search
- Embeddings stored per-model in `semantic_model_embeddings` (face granularity, filtered by `model_id`)
- Query → ONNX tokenizer/model → pgvector cosine distance → hydrate via `CardFace → Card`
- Active model is determined by `semantic_models.is_active`; index polls DB every `SEMANTIC_ACTIVE_MODEL_POLL_SECONDS` seconds
- Model artifacts (ONNX bundle zip) stored in S3-compatible storage; materialized to `SEMANTIC_TEMP_DIR` on demand
- Semantic endpoints return 503 if no active model exists in the registry

### API routes
| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Root health check |
| `/health` | GET | `{"status": "ok"}` |
| `/version` | GET | `{"version": API_VERSION}` |
| `/oracle-samples` | GET | Random oracle text and keyword samples for the UI |
| `/search` | GET | Name-based card search (param: `q`) |
| `/card/{oracle_id}` | GET | Card detail with faces |
| `/similar-cards` | GET | Semantic search (params: `oracle_id` or `q`, `face_ix`, `limit`, `offset`, filters) |
| `/telemetry/client-error` | POST | Client error ingest |
| `/telemetry/analytics` | POST | Frontend analytics ingest |
| `/admin/semantic-models` | GET | List all registered semantic models |
| `/admin/semantic-models` | POST | Register a new semantic model (bundle zip body) |
| `/admin/semantic-models/{model_id}` | GET | Get semantic model detail |
| `/admin/semantic-models/{model_id}/artifacts` | GET | List model artifacts |
| `/admin/semantic-models/{model_id}/promote` | POST | Queue promotion job for a model |
| `/admin/semantic-jobs` | GET | List all semantic jobs |
| `/admin/semantic-jobs/{job_id}` | GET | Get job detail |
| `/admin/semantic-jobs/train` | POST | Create a training job |
| `/admin/semantic-jobs/promote` | POST | Create a promotion job |

Filters on `/similar-cards`: `card_type`, `colors`, `cmc_min`, `cmc_max`, `format`, `rarity`, `color_feature` (`"identity"` | `"colors"`), `match_mode` (`"at_least"` | `"at_most"` | `"exact"`)

### Key files
- `api/main.py` — FastAPI app, lifespan, all routes, CORS middleware, exception handlers
- `core/models.py` — ORM: 9 tables with composite PKs for card_faces and embeddings
- `core/db_init.py` — runs `alembic upgrade head` on every startup; advisory locking for concurrency; migration state FSM (READY → MIGRATING → FAILED)
- `ingest/data_builder.py` — stale-aware Scryfall bulk ingest, card derivation, tag sync, uniqueness scoring
- `embed/pipeline.py` — offline dataset export, fine-tune, ONNX export, re-embedding, and eval
- `embed/index.py` — runtime: lazy-loads ONNX model, encodes queries, pgvector cosine search with server-side filters
- `embed/model_registry.py` — model materialization, embedding population, activation, and promotion logic
- `embed/artifacts.py` — S3 artifact upload/download and recording
- `embed/registration.py` — bundle parsing and model registration
- `embed/semantic_jobs.py` — job queue: create, claim, heartbeat, succeed/fail
- `embed/promote.py` — promotion worker entry point
- `embed/semantic_state.py` — semantic data version tracking
- `frontend/src/lib/api.ts` — fetch client with `searchCards`, `getCard`, `getSimilarCards`, `searchOracleText`, and helpers

### Frontend conventions
- Server state: TanStack Query; routing state: React Router params/query string; transient UI: component state
- UI components do not fetch directly — use `src/lib/api.ts`
- Filters (color, CMC, type, rarity, format) are applied server-side in `embed/index.py`

## Operational notes

- `/search` is still name-based; semantic free-text search runs through `/similar-cards?q=...`
- API startup queries the registry for the active semantic model; returns `503` from semantic endpoints until one is promoted
- `scryfall-sync` is a one-shot worker; it can skip download/ingestion entirely when DB metadata already matches the latest Scryfall bulk timestamp
- Model bundles are stored in S3 (`SEMANTIC_ARTIFACT_BUCKET`) and cached locally in `SEMANTIC_TEMP_DIR`

## Branch conventions

- `main` — production releases (protected)
- `develop` — active development, PRs merge here first
- `production` — alternative production channel
- Feature branches: `feat/<name>`, fixes: `fix/<name>`

## Git commits

- Use `type: message` commit subjects
- Allowed types: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`
- Keep subjects imperative, concise, and without a trailing period
- Example: `fix: handle empty oracle query`

## Environment variables

**Backend:**
| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | Required in production (Railway injects); overrides `DB_*` vars |
| `DB_USER` | `oracle` | Local Postgres user |
| `DB_PASSWORD` | — | Required when `DATABASE_URL` is absent |
| `DB_HOST` | `localhost` | |
| `DB_PORT` | `5432` | |
| `DB_NAME` | `mtg_search` | |
| `DB_POOL_SIZE` | `3` | |
| `DB_POOL_MAX_OVERFLOW` | `2` | |
| `DB_POOL_RECYCLE` | `3600` | |
| `DB_POOL_TIMEOUT` | `30` | |
| `ORACLE_TUTOR_API_ENV` | `development` | `development` \| `production` |
| `ORACLE_TUTOR_API_CORS_ORIGINS` | — | Comma-separated allowed origins |
| `SEMANTIC_BASE_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Base model for training |
| `SEMANTIC_RUNS_DIR` | `data/semantic/runs` | Output root for semantic pipeline runs |
| `SEMANTIC_ACTIVE_MODEL_POLL_SECONDS` | `5` | How often the API checks for a new active model |
| `SEMANTIC_TEMP_DIR` | `$TMPDIR/mtg-search-semantic-models` | Local cache for materialized model bundles |
| `SEMANTIC_ONNX_INTRA_OP_THREADS` | `1` | ONNX Runtime intra-op thread count |
| `SEMANTIC_ONNX_INTER_OP_THREADS` | `1` | ONNX Runtime inter-op thread count |
| `SEMANTIC_JOB_HEARTBEAT_SECONDS` | `600` | Promote worker heartbeat interval |
| `SEMANTIC_JOB_STALE_SECONDS` | `1200` | Seconds before a running job is considered stale |
| `HF_HOME` | `data/huggingface` | Hugging Face cache directory |
| `ORACLE_TUTOR_LOG_TO_FILES` | — | Enable file logging |
| `SEMANTIC_ARTIFACT_ENDPOINT` | — | S3-compatible endpoint URL for artifact storage |
| `SEMANTIC_ARTIFACT_ACCESS_KEY_ID` | — | S3 access key ID for artifact storage |
| `SEMANTIC_ARTIFACT_SECRET_ACCESS_KEY` | — | S3 secret access key for artifact storage |
| `SEMANTIC_ARTIFACT_REGION` | `auto` | S3 region for artifact storage |
| `SEMANTIC_ARTIFACT_BUCKET` | — | S3 bucket name for semantic model artifacts |

**Frontend:**
| Variable | Notes |
|---|---|
| `VITE_API_URL` | API base path (default `/api`) |
| `VITE_APP_URL` | App URL used for canonical SEO links |

## Dev workflows

### Local dev
```bash
docker compose up --build   # db + api + frontend + one-shot scryfall-sync
```

### Backend (run in `backend/`)
```bash
uv sync --all-extras --group dev    # once

uv run ruff check src/ --fix        # lint
uv run basedpyright src/            # type check (errors only; ~546 reportAny warnings are noise)
uv run pytest -x -q                 # tests

# Run scryfall-sync manually:
uv run python -m ot_backend.ingest.main --strict --trigger-type manual

# Run semantic pipeline:
uv run python -m ot_backend.embed.pipeline

# Apply migrations standalone:
uv run alembic upgrade head
```

### Frontend (run in `frontend/`)
```bash
npm install        # once
npm run dev        # localhost:5173, proxies /api to backend
npm run lint
npm run test
npm run build
```

## Rules

- Backend versioned independently from frontend: `backend/pyproject.toml` = `2.0.0`, `frontend/package.json` = `2.0.0`
- Worker is a one-shot container; runs daily via Railway Cron and exits
- Never run destructive Alembic migrations in production without reviewing the migration file first
- Backend tests run against SQLite in-memory — pgvector ops, trigram, JSONB, and extension DDL are not covered by automated tests
- `DATABASE_URL` is required in production; `DB_PASSWORD` is mandatory when `DATABASE_URL` is absent
