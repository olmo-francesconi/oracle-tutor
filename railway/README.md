# Railway env templates

Per-service templates for `railway variables --set`. Fill in the un-suffixed file
(e.g. `api.env`), keep it gitignored, push from it.

| Template | Service | Notes |
|---|---|---|
| `api.env.example` | `api` | FastAPI backend; needs DB ref, admin auth, CF Access, R2 creds |
| `ingest-worker.env.example` | `ingest-worker` | Scryfall sync cron; only needs DB + role |
| `frontend.env.example` | `frontend` | Vite build + nginx runtime; no secrets |
| `db.env.example` | `db` | Postgres — Railway auto-generates everything |

## Push workflow

All Railway tooling is scoped to this directory — `railway link` and `push.sh`
both run from inside `railway/`.

```bash
cd railway/

# One-time link
railway link              # pick workspace/project/environment, ESC on the service prompt

# For each service, fill the template:
cp api.env.example api.env
# ... edit api.env, fill blanks ...

# Push:
./push.sh api             # one service
./push.sh all             # api + ingest-worker + frontend sequentially
ENV=production ./push.sh api   # explicit environment (default production)
```

`db` needs no push — Railway's Postgres template auto-generates everything.

## What deliberately isn't on Railway

These are local-only and must never be set on a Railway service:

- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `MODAL_ENVIRONMENT` — only used by
  `backend/scripts/train_model.py` and the operator TUI.
- `SEMANTIC_LLM_*` — local query generation only.
- `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST`, `DB_PORT` — superseded by
  `DATABASE_URL` from the Postgres service binding.
- `OT_ALLOW_SCHEMA_RESET` — local dev escape hatch only.
