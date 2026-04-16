# Oracle Tutor — Architecture Refactor Roadmap

## Motivation
Code review identified:
- ~1,800 lines of hand-built ML infrastructure (model registry, job queue, artifact storage) that standard tools handle better
- Monolithic API file (1,115 lines) with 30 route handlers
- Broken CI (wrong Dockerfile reference), redundant nginx config
- Frontend components too large (AdminPage 931 lines, SearchShell 670 lines)
- Dead code and a deprecated table

## Phases

### Phase 1: Dead Code Removal
- Remove deprecated `CardFaceSemanticEmbedding` table + ORM class
- Delete unused functions: `normalize_card_data`, `load_existing_cards_map` (data_builder.py), `_load_embeddings_from_file` (pipeline.py)
- Delete unused frontend: `CardOverlay.tsx`, `isErrorReportingConfigured()`, unused type interfaces
- Remove `uvicorn` from API dependencies (app uses hypercorn)

### Phase 2: Docker / CI Fixes
- Fix `ci.yml`: reference `Dockerfile.ingest-worker` (was `Dockerfile.scryfall-sync`)
- Add CI jobs for `train-worker` and `promotion-worker` Dockerfiles
- Consolidate nginx: extract shared proxy snippet, parameterize DNS resolver
- Document Cloudflare-specific `set_real_ip_from` assumption

### Phase 3: API Router Split
- Split `api/main.py` into `routers/admin.py`, `routers/telemetry.py`, `routers/search.py`
- Move mutable globals (`_oracle_text_pool`, `_home_term_pool`) to `app.state`
- Move CORS config into `core/config.py`
- Migrate frontend from model-scoped promote endpoint to jobs endpoint

### Phase 4: Backend Misc Cleanup
- Move `parse_version()` from config.py to db_init.py
- Fix `huggingface_cache_dir()` side effects
- Add proper `migration_state` column to `system_metadata`
- Fix fragile `log_performance` decorator
- Move `compute_and_store_uniqueness_scores` to embed subsystem

### Phase 5: Frontend Component Splits
- AdminPage.tsx → StatusBadge, ModelTable, DatasetTable, JobList components
- SearchShell.tsx → HomeView, ResultsView, useUrlSync hook
- Move inline `.ot-slider` CSS to styles.css
- Standardize arbitrary breakpoints into @theme tokens

### Phase 6: MLflow + RQ Infrastructure
- Add dependencies: `rq`, `redis`, `mlflow-skinny`
- Add Docker services: Redis (broker), MLflow tracking server
- Create `embed/mlflow_bridge.py` — thin MLflow client wrapper

### Phase 7: RQ Job Queue
- Create `embed/task_queue.py` and `embed/tasks.py`
- Replace DB-polled job queue with RQ enqueue/worker pattern
- Keep `semantic_jobs` table for history
- Replace per-worker containers with `rq worker --burst`

### Phase 8: MLflow Model Tracking
- Dual-write: log runs to MLflow alongside existing custom registry
- Enrich admin API responses with MLflow metadata
- Both systems active simultaneously (safe transition)

### Phase 9: Pipeline Subcommands
- Replace if-elif CLI dispatch in `pipeline.py main()` with argparse subparsers
- Subcommands: run, export, register, promote, eval

### Phase 10: Registry Migration & Cleanup
- One-time migration script: backfill existing models into MLflow
- Simplify `model_registry.py`: download from MLflow artifact store
- Remove custom artifact upload code, advisory locks, polling functions
- Delete deprecated worker entrypoints (promote.py, dataset_worker.py, train_worker.py)

## Architecture After Refactor
- **Model tracking**: MLflow (experiment comparison, artifact storage, model versioning)
- **Job queue**: RQ + Redis (simple task dispatch, burst workers)
- **API**: FastAPI with router modules (admin, search, telemetry)
- **Embeddings**: pgvector (unchanged — MLflow can't do cosine search)
- **Runtime inference**: ONNX Runtime (unchanged)

## Key Decisions
- **RQ over Celery**: 3 job types, low throughput, `--burst` matches one-shot Railway containers
- **MLflow tracking server**: adds Docker service but gives UI for experiment comparison
- **Keep unused tables**: `card_relationships`, `tag_ancestor_map` will be used in future features
