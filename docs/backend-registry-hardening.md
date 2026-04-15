# Backend Registry Hardening

> **Status:** Planned — implement in stages  
> **Branch:** develop  
> **Scope:** Model registry pipeline introduced in the current develop cycle

## Background

The model registry pipeline (`model_registry.py`, `semantic_state.py`, `train_worker.py`, `promote.py`, `/admin/semantic-models/*` routes) was reviewed and 8 issues were identified. This document captures the full remediation plan to be implemented in stages.

**Railway constraint:** Railway volumes are per-service and cannot be shared across services. A Railway Bucket (S3-compatible object storage) is the chosen solution for artifact sharing, mirrored locally with MinIO in Docker Compose.

## Rollout Assumptions

- This plan is intentionally **breaking** for the semantic model registry. Legacy locally stored model blobs do not need to remain usable.
- Short downtime while rebuilding the first working model after the refactor is acceptable.
- Backward compatibility for pre-S3 artifacts is explicitly out of scope. The post-refactor system should be clean and S3-native rather than carrying transitional fallback logic.
- The current manual promotion trigger path is temporary. It is acceptable for this phase, with a follow-up task to design a proper re-embedding dispatch mechanism.
- If needed, semantic registry tables can be cleared before the production 2.0.0 cutover to avoid carrying forward bad or ambiguous pre-refactor state.

---

## Issues & Fixes

### Issue 1 — HIGH: ONNX blobs stored in Postgres

**Root cause:** `SemanticModel.artifact_bundle_bytes` is `LargeBinary NOT NULL` — 80–200 MB per model, loaded eagerly on any ORM access. Bloats DB, backups, and RAM.

**Fix: Railway Bucket (S3-compatible object storage)**

Use a [Railway Bucket](https://docs.railway.com/storage-buckets) (`https://storage.railway.app`) for artifact storage. It is shared across all Railway services via variable references, and mirrored locally with **MinIO** in Docker Compose using identical env vars and the same boto3 client code.

**Artifact key scheme:** `semantic-registry/{model_id}/bundle.zip`

**New dependency:** `boto3` added to `pyproject.toml` base dependencies.

**New config in `core/config.py`:**
```python
def artifact_bucket_client():
    import boto3
    from botocore.client import Config
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("ENDPOINT"),          # Railway: https://storage.railway.app
        aws_access_key_id=os.getenv("ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("SECRET_ACCESS_KEY"),
        region_name=os.getenv("REGION", "auto"),
        config=Config(signature_version="s3v4"),
    )

def artifact_bucket_name() -> str:
    return os.environ["BUCKET"]
```

**`model_registry.py` changes:**
- `create_semantic_model`: after DB insert, upload bundle bytes to S3 key `semantic-registry/{model_id}/bundle.zip`; store key in new `artifact_s3_key` column
- `materialize_semantic_model`: download from S3 using `artifact_s3_key`, extract to temp dir (existing extraction logic unchanged)
- `artifact_bundle_bytes` is never read from DB again
- No dual-read fallback will be added. Rows without a valid S3 object are considered unsupported legacy state.

**DB migration `0004`:**
- Add `artifact_s3_key` String column (nullable)
- Make `artifact_bundle_bytes` nullable
- Existing rows are not backfilled. If pre-refactor semantic models exist, they may be discarded before or during rollout.
- Future cleanup migration will `DROP COLUMN artifact_bundle_bytes` once the new S3-only flow is stable

**Rollout note:** This is a deliberate clean break. For the 2.0.0 rollout, it is acceptable to clear `semantic_models` and `semantic_model_embeddings` rather than preserve legacy bundles.

**Docker Compose — MinIO service:**
```yaml
minio:
  image: minio/minio:latest
  command: server /data --console-address ":9001"
  ports:
    - "9000:9000"
    - "9001:9001"
  environment:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin123
  volumes:
    - minio_data:/data
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
    interval: 5s
    timeout: 5s
    retries: 5

minio-init:
  image: minio/mc:latest
  depends_on:
    minio:
      condition: service_healthy
  entrypoint: >
    /bin/sh -c "
    mc alias set local http://minio:9000 minioadmin minioadmin123 &&
    mc mb --ignore-existing local/semantic-artifacts;
    "
  restart: "no"
```

**Shared env vars for all backend services in docker-compose:**
```yaml
environment:
  - ENDPOINT=http://minio:9000
  - ACCESS_KEY_ID=minioadmin
  - SECRET_ACCESS_KEY=minioadmin123
  - BUCKET=semantic-artifacts
  - REGION=us-east-1
```

**Railway setup (one-time, manual via dashboard):**
1. Add a Storage Bucket service to the Railway project
2. In each service (api, train-worker, promotion-worker), inject credentials via variable references:
   `${{bucket.ENDPOINT}}`, `${{bucket.ACCESS_KEY_ID}}`, `${{bucket.SECRET_ACCESS_KEY}}`, `${{bucket.BUCKET}}`, `${{bucket.REGION}}`

**Files to change:**
- `backend/pyproject.toml`
- `backend/src/ot_backend/core/config.py`
- `backend/src/ot_backend/core/models.py`
- `backend/src/ot_backend/embed/model_registry.py`
- `backend/alembic/versions/0004_artifact_s3_and_slug_unique.py`
- `docker-compose.yml`

---

### Issue 2 — MEDIUM: `_PROMOTION_LOCK` is process-local only

**Root cause:** `threading.Lock()` only protects within one process. Multiple Railway service replicas or concurrent worker runs can race.

**Fix:** Replace with a DB-enforced global guard inside `begin_semantic_model_promotion`. The goal is to guarantee that at most one model can be in `embedding` at a time across all processes and replicas. `threading.Lock()` remains only as an in-process secondary guard.

Preferred implementation options, in order:
1. A partial unique index that allows only one row with `status = 'embedding'`
2. A dedicated singleton lock row/table updated transactionally
3. A Postgres advisory lock if we want the lightest schema change

`SELECT ... FOR UPDATE` on the candidate row alone is not sufficient, because two different candidate rows can still race each other.

Implementation should look like:
```python
with SessionLocal() as db:
    with db.begin():
        model = db.get(SemanticModel, model_id, with_for_update=True)
        if model is None:
            raise KeyError(...)
        if model.is_active and model.status == SEMANTIC_MODEL_STATUS_ACTIVE:
            raise ValueError(...)

        # Acquire the global promotion guard here using the chosen mechanism.
        # If another promotion is already active, fail before mutating state.

        model.status = SEMANTIC_MODEL_STATUS_EMBEDDING
```

**Files:**
- `backend/src/ot_backend/embed/model_registry.py`
- `backend/alembic/versions/0004_artifact_s3_and_slug_unique.py` if we use the partial unique index approach

---

### Issue 3 — HIGH: Promotion runs in API background thread

**Root cause:** `_start_semantic_model_promotion` spawns a `daemon=True` thread inside the FastAPI process. Re-embedding 30k faces is CPU/DB-intensive; a pod restart leaves the model stuck in `embedding` with no recovery path.

**Fix:** Remove the background thread from the API entirely.

The `POST /admin/semantic-models/{id}/promote` endpoint will:
1. Call `begin_semantic_model_promotion(model_id)` — marks status as `embedding`
2. Return 202 Accepted immediately

Actual promotion is always performed by the dedicated promotion-worker:
- **Train-worker path:** `--promote-after-register` calls `run_semantic_model_promotion` synchronously inside the train-worker container
- **Manual path:** run `oracle-tutor-promotion-worker --model-id <id>` as a one-shot Railway job

`begin_semantic_model_promotion` no longer holds `_PROMOTION_LOCK` on return. `run_semantic_model_promotion` performs its own guard check (Issue 2's DB check) at entry.

**Temporary workflow note:** This manual trigger path is intentionally temporary. It is acceptable for the hardening phase even though the API does not yet dispatch the promotion job directly. A follow-up task should introduce a real handoff mechanism so `POST /promote` can enqueue or launch the worker automatically.

**Files:**
- `backend/src/ot_backend/api/main.py` — remove `_start_semantic_model_promotion`
- `backend/src/ot_backend/embed/model_registry.py` — `begin_semantic_model_promotion` / `run_semantic_model_promotion`

---

### Issue 4 — MEDIUM: Lock release bug in `begin_semantic_model_promotion`

**Root cause:**
```python
except Exception:
    _PROMOTION_LOCK.release()  # raises RuntimeError if lock not already held — masks original exception
    raise
```

**Fix:** Track lock acquisition with a boolean flag:
```python
lock_acquired = _PROMOTION_LOCK.acquire(blocking=False)
if not lock_acquired:
    raise RuntimeError("Promotion already running in this process.")
try:
    ...
except Exception:
    if lock_acquired:
        _PROMOTION_LOCK.release()
    raise
```

**Files:** `backend/src/ot_backend/embed/model_registry.py`

---

### Issue 5 — MEDIUM: Staleness check bypassed when `source_version` is None

**Root cause:** `_ensure_model_is_not_stale` logs a warning and silently returns when `source_version is None`, allowing promotion of unversioned models.

**Fix:** Always raise:
```python
if source_version is None:
    raise RuntimeError(
        f"Semantic model {model.id} has no source semantic data version recorded. "
        "Promotion blocked to prevent promoting against stale data."
    )
```

Models registered via the normal train-worker pipeline always have a version. Manually-uploaded legacy bundles without a version must be re-registered.

**Files:** `backend/src/ot_backend/embed/model_registry.py`

---

### Issue 6 — LOW: N+1 queries on `/admin/semantic-models` list

**Root cause:** `count_semantic_model_embeddings` is called per model inside the list loop — one `COUNT` query per model.

**Fix:** Add a batch aggregation function:
```python
def count_semantic_model_embeddings_batch(db: Session, model_ids: list[int]) -> dict[int, int]:
    if not model_ids:
        return {}
    rows = db.execute(
        select(SemanticModelEmbedding.model_id, func.count().label("cnt"))
        .where(SemanticModelEmbedding.model_id.in_(model_ids))
        .group_by(SemanticModelEmbedding.model_id)
    ).all()
    counts = {row.model_id: row.cnt for row in rows}
    return {mid: counts.get(mid, 0) for mid in model_ids}
```

**Files:**
- `backend/src/ot_backend/embed/model_registry.py` — add `count_semantic_model_embeddings_batch`
- `backend/src/ot_backend/api/main.py` — `admin_list_semantic_models` uses batch function

---

### Issue 7 — LOW: No uniqueness constraint on `slug`

**Root cause:** `ix_semantic_models_slug` is a plain non-unique index. Duplicate slugs can be inserted.

**Fix:** Replace with a unique constraint in migration `0004`:
```python
op.drop_index("ix_semantic_models_slug", table_name="semantic_models")
op.create_unique_constraint("uq_semantic_models_slug", "semantic_models", ["slug"])
```

Catch `IntegrityError` in `POST /admin/semantic-models` and return 409 Conflict.

**Rollout note:** We do not need a legacy duplicate-slug cleanup path. If duplicate semantic model rows already exist before the 2.0.0 cutover, clearing registry data is acceptable.

**Files:**
- `backend/alembic/versions/0004_artifact_s3_and_slug_unique.py`
- `backend/src/ot_backend/api/main.py`

---

### Issue 8 — LOW: Private function coupling across modules

**Root cause:** `train_worker.py` imports `_promote_model` from `pipeline.py` (a private implementation detail), creating fragile cross-module coupling.

**Fix:**
```python
# train_worker.py — replace _promote_model with the public API
from .model_registry import run_semantic_model_promotion

success = run_semantic_model_promotion(model_id, embed_batch_size=args.embed_batch_size)
return 0 if success else 1
```

Remove `_promote_model` from `pipeline.py` if no other callers remain (verify with grep).

**Files:**
- `backend/src/ot_backend/embed/train_worker.py`
- `backend/src/ot_backend/embed/pipeline.py`

---

### Bonus — LOW: `RequestSizeLimitMiddleware` path prefix fragility

`request.url.path.startswith("/admin/semantic-models")` is a magic string. Extract to a constant so it stays in sync if the route prefix changes:

```python
_SEMANTIC_ADMIN_PREFIX = "/admin/semantic-models"
```

**Files:** `backend/src/ot_backend/api/main.py`

---

## Migration Summary

**File:** `backend/alembic/versions/0004_artifact_s3_and_slug_unique.py`

```
ALTER TABLE semantic_models ADD COLUMN artifact_s3_key VARCHAR (nullable)
ALTER TABLE semantic_models ALTER COLUMN artifact_bundle_bytes DROP NOT NULL
DROP INDEX ix_semantic_models_slug
ADD UNIQUE CONSTRAINT uq_semantic_models_slug (slug)
```

**`DB_SCHEMA_VERSION`:** `2.7.0` → `2.8.0` in `backend/src/ot_backend/core/config.py`

**Operational note:** If we choose to reset semantic registry state before production 2.0.0, migration compatibility for existing semantic model rows is not required.

---

## Implementation Stages

| Stage | Issues | Notes |
|---|---|---|
| 1 | Issue 7, Issue 6, Issue 8, Bonus | Pure code fixes, no infra changes. Safe to ship first. |
| 2 | Issue 4, Issue 5 | Bug fixes in promotion logic. No DB changes. |
| 3 | Issue 2, Issue 3 | Promotion architecture change — remove background thread. Requires coordination with Railway deploy. |
| 4 | Issue 1 | S3 migration — requires Railway Bucket provisioning and MinIO in docker-compose. Biggest change. |

---

## Implementation Checklist

### Stage 0 — Lock Decisions

- Artifact storage is S3-only after the refactor. No dual-read fallback and no backfill path.
- Legacy semantic registry rows are disposable. If needed, clear `semantic_models` and `semantic_model_embeddings` before the 2.0.0 cutover.
- Promotion concurrency must use a DB-enforced global guard.
- Preferred guard: a partial unique index allowing only one row where `status = 'embedding'`.
- `POST /promote` returning `202` without dispatching the worker is acceptable temporarily, but the manual promotion-worker workflow must be documented.

### Stage 1 — Safe Code Fixes

- Add `count_semantic_model_embeddings_batch` in `backend/src/ot_backend/embed/model_registry.py`.
- Update `admin_list_semantic_models` in `backend/src/ot_backend/api/main.py` to use the batch count.
- Replace private `_promote_model` imports in `train_worker.py` and `promote.py`.
- Remove `_promote_model` from `pipeline.py` if no callers remain.
- Extract `"/admin/semantic-models"` into a constant in `api/main.py`.

### Stage 2 — Promotion Logic Fixes

- Fix `_PROMOTION_LOCK` release handling in `begin_semantic_model_promotion`.
- Change `_ensure_model_is_not_stale` to raise when `source_version is None`.
- Add tests covering missing source version and lock-release behavior.

### Stage 3 — Promotion Architecture

- Remove `_start_semantic_model_promotion` thread spawning from `api/main.py`.
- Make `POST /admin/semantic-models/{id}/promote` only mark the model as `embedding` and return `202`.
- Ensure `run_semantic_model_promotion` can be called safely from worker entrypoints.
- Update `train_worker.py` so `--promote-after-register` runs promotion synchronously via the public registry API.
- Update `promote.py` to use the same public path.

### Stage 4 — Global Promotion Guard

- Add the DB-level invariant that only one model can be in `embedding`.
- Recommended implementation:
  - add a partial unique index in Alembic on `semantic_models(status)` filtered to `status = 'embedding'`
  - catch `IntegrityError` when transitioning a model into `embedding`
  - return a clear "promotion already in progress" error
- Keep `_PROMOTION_LOCK` only as an in-process fast-fail optimization.
- Add concurrency coverage if feasible, otherwise integration coverage around duplicate promotion attempts.

### Stage 5 — S3 Artifact Refactor

- Add `boto3` to `backend/pyproject.toml`.
- Add bucket client helpers to `backend/src/ot_backend/core/config.py`.
- Update `SemanticModel` in `backend/src/ot_backend/core/models.py`:
  - add `artifact_s3_key`
  - make `artifact_bundle_bytes` nullable
- Update `create_semantic_model`:
  - validate bundle
  - insert row
  - upload bundle to S3
  - persist `artifact_s3_key`
  - set `artifact_bundle_bytes` to `NULL` in the final stored row
- Update `materialize_semantic_model`:
  - require `artifact_s3_key`
  - download from S3
  - extract to temp dir
  - do not read DB blob
- Treat missing S3 artifacts as unsupported legacy state, not something to recover from.

### Stage 6 — Migration

- Create `backend/alembic/versions/0004_artifact_s3_and_slug_unique.py`.
- Include:
  - `artifact_s3_key` column
  - `artifact_bundle_bytes` nullable
  - unique slug constraint
  - partial unique index for `status = 'embedding'`
- Bump `DB_SCHEMA_VERSION` in `backend/src/ot_backend/core/config.py`.

### Stage 7 — Local Infra

- Add MinIO and `minio-init` to `docker-compose.yml`.
- Add shared backend env vars for `ENDPOINT`, `ACCESS_KEY_ID`, `SECRET_ACCESS_KEY`, `BUCKET`, and `REGION`.
- Verify all backend services use the same S3 config locally.

### Stage 8 — API Behavior

- Catch slug uniqueness violations in `POST /admin/semantic-models` and return `409`.
- Ensure the promote endpoint returns `202` consistently when marking starts.
- Ensure failed worker runs move model state to `failed` with a useful error message.

### Stage 9 — Tests And Verification

- Backend tests:
  - registry creation stores artifacts in S3 and not DB
  - materialization reads from S3
  - duplicate slug returns `409`
  - list endpoint avoids N+1 behavior
  - promotion blocks when no source version exists
  - only one model can enter `embedding`
- Run:
  - `cd backend && uv run pytest -x -q`
  - `cd backend && uv run basedpyright src/`
  - `cd backend && uv run ruff check src/ --fix`
- Migration round-trip:
  - `cd backend && uv run alembic upgrade head`
  - `cd backend && uv run alembic downgrade -1`
  - `cd backend && uv run alembic upgrade head`

### Stage 10 — Cutover

- Provision the Railway Bucket.
- Inject bucket vars into API, train-worker, and promotion-worker services.
- If chosen, clear semantic registry tables before the 2.0.0 deploy.
- Deploy migration and code together.
- Rebuild and register the first model in the new S3-backed flow.
- Promote it using the temporary manual worker workflow.

### Definition Of Done

- New semantic models are stored only in S3.
- API no longer spawns promotion threads.
- Only one promotion can be in `embedding` globally.
- Duplicate slugs are rejected.
- Legacy local and DB-backed models are intentionally unsupported.
- A fresh model can be registered and promoted end-to-end in local Docker and Railway.

---

## Verification

```bash
cd backend

uv run pytest -x -q
uv run basedpyright src/
uv run ruff check src/ --fix

# Migration round-trip
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Integration (local Docker):
```bash
docker compose up --build
# MinIO console: http://localhost:9001  (minioadmin / minioadmin123)

# Check:
# 1. POST /admin/semantic-models → bundle appears in MinIO at semantic-registry/{id}/bundle.zip
# 2. artifact_bundle_bytes is NULL in Postgres
# 3. List endpoint uses single COUNT query (no N+1)
# 4. POST /promote returns 202, no background thread spawned in API
# 5. Promotion-worker --model-id <id> downloads from MinIO, computes embeddings, activates model
# 6. Duplicate slug → 409
# 7. Model with no source_semantic_data_version → promotion raises, not warns
```
