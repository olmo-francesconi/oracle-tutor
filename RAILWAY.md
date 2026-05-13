# Railway deployment — streamlined architecture

This is the deployment guide for the **streamlined architecture** (post-2026-05 rethink). For the older multi-worker Railway shape, see git history (`RAILWAY.md` before this rewrite).

## The shape

Five things run on Railway. Everything else runs from your laptop.

```
┌──────────────────── Railway ─────────────────────┐
│  frontend (nginx)  ──►  api (FastAPI)            │
│                              │                   │
│                              ▼                   │
│                         db (pgvector)            │
│                              ▲                   │
│                              │                   │
│  ingest-worker (cron, one-shot)                  │
└──────────────────────────────────────────────────┘
                               ▲
                               │  TLS + password
                               │
┌──────────────────── Your laptop ─────────────────┐
│  backend/scripts/build_dataset.py    ──► R2 + DB        │
│  backend/scripts/train_model.py      ──► Modal + R2 + DB │
│  backend/scripts/promote_model.py    ──► DB (embeddings) │
└──────────────────────────────────────────────────┘

┌──────────────────── Cloudflare R2 ───────────────┐
│  Dataset artifacts (training pairs)              │
│  Model bundles (ONNX zips)                       │
└──────────────────────────────────────────────────┘
```

**Why this shape:**

- Things that must run on a schedule (ingest) or serve traffic (api, frontend) live on Railway.
- Things that run rarely, are heavy, and are operator-initiated (dataset gen, training, promotion) are local scripts. They use Modal for compute when needed but the orchestration is on your machine.
- The admin panel becomes a **read-only explorer** for models, datasets, and ingest history — no mutation surface in the UI.

## Components

| Component | Where | Purpose | Cadence |
|---|---|---|---|
| `frontend` | Railway | nginx serving SPA + proxying `/api` | always on |
| `api` | Railway | FastAPI: search, similar-cards, admin read endpoints | always on |
| `db` | Railway | Postgres 17 + pgvector | always on |
| `ingest-worker` | Railway Cron | Daily Scryfall sync | `0 2 * * *` |
| `backend/scripts/build_dataset.py` | Laptop | Read card_faces, build pairs, upload to R2 | as needed |
| `backend/scripts/train_model.py` | Laptop → Modal | Fine-tune base model, upload bundle to R2, register in DB | as needed |
| `backend/scripts/promote_model.py` | Laptop | Pull bundle from R2, embed all faces, flip `is_active` | as needed |
| Cloudflare R2 | Cloudflare | Dataset + model bundle storage | always on |
| Modal | Modal | GPU runtime for training (only) | per training run |
| Cloudflare Access | Cloudflare | Identity gate on admin subdomain | always on |

## Admin panel = model explorer

The admin panel keeps its Cloudflare-Access gate and admin-host check, but the API surface shrinks dramatically:

**Kept (read-only):**
- `GET /admin/auth/token` — still needed to authenticate the SPA
- `GET /admin/semantic-models` + `GET /admin/semantic-models/{id}` + `/artifacts`
- `GET /admin/semantic-datasets` + `GET /admin/semantic-datasets/{id}` + `/artifacts`
- `GET /admin/semantic-jobs` — re-purposed as **history log** (each script run inserts a completed row for audit)

**Removed:**
- `POST /admin/semantic-models` (registration moves to scripts)
- `POST /admin/semantic-models/{id}/promote`
- `POST /admin/semantic-jobs/dataset`
- `POST /admin/semantic-jobs/train`
- `POST /admin/semantic-jobs/promote`
- `GET /admin/semantic-base-models` / `GET /admin/semantic-train-options` (UI doesn't pick options anymore)

Admin UI becomes two tabs: **Models** (list, view artifact links) and **Datasets** (list, view artifact links). No history — `semantic_jobs` is dropped entirely.

The `semantic/model_promotion.py`, `semantic/bundle_registration.py`, and `semantic/artifacts.py` modules stay — the local scripts call them as a library. The old worker modules and `Dockerfile.worker`, plus the `semantic_jobs` table (Alembic migration `0002_drop_semantic_jobs`), are gone.

## Deploy: clean-slate steps

1. **Cloudflare R2** — create bucket `oracletutor-semantic-artifacts`, generate API token (read+write), record endpoint URL, access key, secret.
2. **Railway Postgres** — add service from `pgvector/pgvector:pg17`, attach volume at `/var/lib/postgresql/data`, run `CREATE EXTENSION vector;`.
3. **Cloudflare Access** — Zero Trust → Apps → self-hosted on `admin.oracletutor.org`, Allow policy for your email. Copy team domain + AUD tag.
4. **DNS** — Cloudflare DNS: apex + admin subdomain both CNAME to `<frontend>.up.railway.app` (proxied).
5. **Deploy `api`** — `backend/Dockerfile`, no public domain. Env:
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   OT_ENV=production
   OT_PUBLIC_URL=https://oracletutor.org
   OT_CORS_ORIGINS=https://oracletutor.org,https://admin.oracletutor.org
   ADMIN_PASSWORD=<32+ chars>
   ADMIN_JWT_SECRET=<64+ chars>
   CF_ACCESS_TEAM_DOMAIN=<team>.cloudflareaccess.com
   CF_ACCESS_AUD=<aud-tag>
   SEMANTIC_ARTIFACT_ENDPOINT=https://<acct>.r2.cloudflarestorage.com
   SEMANTIC_ARTIFACT_ACCESS_KEY_ID=...
   SEMANTIC_ARTIFACT_SECRET_ACCESS_KEY=...
   SEMANTIC_ARTIFACT_BUCKET=oracletutor-semantic-artifacts
   SEMANTIC_ARTIFACT_REGION=auto
   ```
6. **Deploy `frontend`** — `frontend/Dockerfile` target `runtime`, attach both custom domains. Env:
   ```
   PORT=8080
   API_PROXY_TARGET=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000
   ADMIN_HOST=admin.oracletutor.org
   ```
   `NGINX_RESOLVER` is deliberately not set — the `Dockerfile` defaults it to
   `127.0.0.11` (Docker DNS), which is what Railway's network expects. The
   previously-documented IPv6 resolver (`fd12:3456:78::1`) is finicky and
   should be avoided unless you have a reason.
   Build-time:
   ```
   VITE_API_URL=/api
   VITE_APP_URL=https://oracletutor.org
   ```
7. **Deploy `ingest-worker`** — `backend/Dockerfile.worker.ingest`, restart policy "Never", cron `0 2 * * *`. Env: `DATABASE_URL`, `OT_ENV=production`, `OT_SERVICE_ROLE=worker`.
8. **Trigger first ingest** manually from Railway → DB fills with ~30k cards.
9. **Expose DB publicly** — Railway → Postgres → Settings → enable public TCP proxy. Copy the public connection string. Rotate the password to something long.
10. **Local: run scripts** (see below) → first model lands in the DB, embeddings written, `/similar-cards` starts returning 200.

## Local script workflow

Scripts live at `backend/scripts/` and are run with `uv run` from the `backend/` directory (so they pick up the project venv).

Each script loads env vars from `backend/.env` by default. Pass `--prod` to load `backend/.env.prod` instead (gitignored, holds the Railway public DB URL + R2 credentials pointing at production).

```bash
cd backend

# 1) Build a dataset
uv run python -m scripts.build_dataset --prod --name "v3-balanced"
# → uploads dataset.zip to R2, inserts row in semantic_datasets

# 2) Train (calls Modal under the hood)
uv run python -m scripts.train_model --prod --dataset-id <id> --slug v3 \
  --base-model all-MiniLM-L6-v2
# → Modal fine-tunes on GPU, uploads bundle.zip to R2,
#   inserts row in semantic_models (is_active=false)

# 3) Promote
uv run python -m scripts.promote_model --prod --model-id <id>
# → pulls bundle from R2, encodes all card_faces, batch-writes embeddings,
#   single-txn swap of is_active. API picks up the new model on its next poll.
```

The scripts call the same library functions the deleted workers did: `model_promotion.promote_semantic_model`, `bundle_registration.register_model_bundle_bytes`, `modal_train` (via `modal.Function.lookup`), `dataset_service.export_training_dataset_bytes`.

## Friction points

1. **DB on the public internet.**
   Required for local scripts. Mitigation: long random password (`token_urlsafe(48)`), `sslmode=require` (already enforced by psycopg config when the URL contains `sslmode=require`), rotate quarterly. Optional v2: `cloudflared` TCP tunnel + Access policy → DB never exposed.

2. **Local env drift breaks shipping.**
   If your laptop's Python is broken, you can't promote. Mitigation: scripts run via the same Docker image you use in CI:
   ```bash
   docker run --rm --env-file backend/.env.prod -v $(pwd):/work -w /work/backend oraculartutor/worker \
     python -m scripts.promote_model --prod --model-id ...
   ```
   Treat the Docker image as the runtime, not your host Python.

3. **Long transaction over the WAN during promote.**
   30k face embeddings over a flaky wifi connection is asking for trouble. The current promotion code batches inserts and only the final `is_active` swap is one short txn, so a network blip means "rerun from a checkpoint" not "DB corrupted". Verify the batch boundaries survive disconnect cleanly before you trust it on real ops.

4. **`semantic_jobs` is gone.**
   The table is dropped by Alembic migration `0002_drop_semantic_jobs`; the `SemanticJob` ORM model and `semantic_jobs.py` module no longer exist. Admin UI has no history surface — read the model and dataset tables directly if you need an audit trail.

5. **Bootstrap UX is rougher for a new operator.**
   Fresh deploy has no model, `/similar-cards` returns 503 until you train+promote. Acceptable for a solo project. If you ever hand the repo over: either document the 3-script sequence prominently, or check a "starter bundle" into R2 that `promote_model.py --bootstrap` can pull.

6. **Modal credentials only on your laptop.**
   Same as today — `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` never touch Railway. If your laptop dies, the recovery path is "log into Modal on a new machine, re-clone repo, re-run".

7. **Admin panel can't trigger jobs.**
   Cognitive shift: the panel is for observing what's deployed, not operating the pipeline. Use the local scripts for any mutation.
