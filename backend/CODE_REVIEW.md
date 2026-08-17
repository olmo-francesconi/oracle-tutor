# Backend Code Review — Oracle Tutor

Scope: `backend/src/ot_backend` (API, core/DB, semantic, ingest) + Alembic migrations. ~9.3k LOC.
Findings verified against source where load-bearing. Severity reflects production impact.

---

## Critical

### 1. Promotion advisory lock is released before the embed/activate phase
`semantic/model_promotion.py:35-47`
`_try_promotion_advisory_lock` uses `pg_try_advisory_xact_lock`, which auto-releases when the
claiming transaction **commits** at the end of `_claim_model_for_promotion`. The long
`_populate_model_embeddings` + `_activate_model` phases then run with **no lock held**. Two
concurrent promotions can interleave; the `is_active` flip in `_activate_model` is unguarded.
The docstring's claim that the embed+activate phase is safe without re-taking the lock is wrong.
**Fix:** hold a session-level `pg_advisory_lock` for the whole `promote_semantic_model` call,
released in a `finally`.

### 2. No DB constraint enforces a single active model
`core/models.py:303` — `is_active` is a plain boolean; only `slug` is `unique`. Combined with #1,
two concurrent activations can both commit `is_active=true`. `get_active_semantic_model_id` does
`.limit(1)`, silently masking the dual-active state and making which model serves queries
nondeterministic.
**Fix:** `CREATE UNIQUE INDEX ... ON semantic_models (is_active) WHERE is_active`.

### 3. Zip-slip in model bundle extraction
`semantic/model_registry.py:205` — `archive.extractall(extract_dir)` on a bundle pulled from S3,
with no member-name sanitization (`validate_model_bundle` at :65 only checks for *presence* of
required entries). A bundle with `../` members writes outside `extract_dir`. Mitigated by the
bucket being operator-controlled (not public input), but it's defense-in-depth on a path that then
**deserializes a PyTorch model** (`SentenceTransformer(...)` → pickle → potential RCE).
**Fix:** reject members whose `os.path.normpath` escapes `extract_dir`; verify the recorded
`sha256` of the downloaded bytes before extracting/loading.

### 4. Migration-state FSM is dead on the API path
`core/db_init.py:202-217` — `_set_migration_state` (MIGRATING/READY/FAILED) and
`_upsert_schema_version` are only called when `mode == INIT_MODE_WORKER`. In `INIT_MODE_API` the
code runs Alembic but never writes state, so `get_migration_state()` returns the "no row" default
(READY) the entire time an API instance is migrating, and never writes FAILED on error.
`wait_for_migration_ready` therefore can't actually gate API endpoints during an API-driven
migration, and a failed API migration reports READY.
**Fix:** write MIGRATING/READY/FAILED in the API path too, or assert the API never migrates
(schema already at head) and document it.

---

## High

### 5. `match_mode` / `color_feature` are not validated server-side (flagged by 2 reviewers)
`api/routers/search.py:300-301` → `semantic/index.py:255-265`. Both are raw `str` params; allowlist
validation lives only in the frontend `lib/filters.ts`. A direct API caller sending
`match_mode=foo` silently falls through to `at_least`; any `color_feature != "identity"` falls
through to `colors`. Silent wrong results (422 expected), inconsistent with the allowlist-validated
`rarity`/`format`/`card_type`.
**Fix:** type as `Literal[...]` (or `Query(pattern=...)`) so FastAPI rejects bad input.

### 6. Per-IP admin lockout trusts client-controlled `X-Real-IP`
`api/admin_auth.py:53` — `get_admin_client_ip` reads `X-Real-IP` verbatim. If an attacker can set
that header (nginx misconfig/bypass), each spoofed value gets a fresh lockout bucket, defeating
`ADMIN_LOGIN_MAX_FAILURES`. Same untrusted IP is written to `SemanticQueryLog.client_ip`
(`search.py:262`).
**Fix:** derive client IP from a trusted-proxy count (`ProxyHeadersMiddleware`) in production.

### 7. Artifact upload + DB record are not atomic → orphans
`semantic/artifacts.py:139-158`, `bundle_registration.py:181-240` — `put_object` (S3) then DB flush,
with multiple artifacts uploaded before a single `commit()`. A mid-sequence failure leaves S3
objects with rolled-back rows (orphaned blobs) or a committed model with a partial artifact set.
**Fix:** upload all, record all, single commit; delete this-call S3 objects on failure.

### 8. No integrity verification on bundle download
`semantic/model_registry.py:203-205`, `artifacts.py:58-61` — `sha256` is stored but never checked
on download before extraction/model load. A corrupted/tampered S3 object is loaded as-is.
**Fix:** compare `hashlib.sha256(bytes).hexdigest()` to the recorded hash before extract.

### 9. Unbounded `offset` enables a cheap DoS on the HNSW scan
`api/routers/search.py:190,319` — `offset` is only `ge=0`; `limit+offset+1` rows are fetched.
`offset=10_000_000` forces the index to materialize ~10M candidates. (`/search` has the same hole.)
**Fix:** cap with `Query(0, ge=0, le=1000)`.

### 10. JSON/JSONB drift + missing `ondelete` on `Card.scryfall_id`
`core/models.py` — `CardRaw.color_identity/keywords/legalities` use `JSON` while `Card`/`CardFace`
use `JSONB`; `Card.scryfall_id` FK to `cards_raw.id` has no `ondelete`, so deleting a raw printing a
`cards` row references raises an FK violation during re-derivation. `env.py`'s `compare_type=True`
gives false drift-detection comfort — the project uses `create_all`, not autogenerate.
**Fix:** unify on JSONB; set an explicit `ondelete` policy on `Card.scryfall_id`.

### 11. Failed index materialization throws away a working index and blocks retry
`semantic/index.py:481-486` — on a transient S3/ONNX failure the except sets `_index = None` **and**
`_loaded_model_id = active_model_id`, so the unchanged-ID fast path returns `None` (503) without
retrying until a *different* model is promoted. One flaky download permanently degrades to 503.
**Fix:** on failure keep any healthy `_index` and leave `_loaded_model_id` unchanged so the next
poll retries.

### 12. Scryfall 429 handling resets the session instead of honoring `Retry-After`
`ingest/fetch_tags.py:518-526,606-647` — a 429 returns `RESET_SESSION` (rebuilds CSRF session,
flat 5s sleep, extra homepage GET — more load on the throttled host). After `MAX_SESSION_RESETS=5`
the card is **silently dropped** → silent data loss under sustained 429s. `Retry-After` ignored.
**Fix:** on 429 sleep `Retry-After`/exponential within the same session; add a circuit-breaker that
aborts the run rather than dropping cards.

### 13. Advisory lock on migrations has no `lock_timeout`
`core/db_init.py:48-66` — the dedicated lock connection takes `pg_advisory_lock` with no timeout.
If Alembic hangs (DDL contention, slow `CREATE EXTENSION`), every booting instance blocks forever,
and the API's 30s `wait_for_migration_ready` can't help (state row never written, see #4).
**Fix:** set `lock_timeout`/`statement_timeout` on the lock connection or use
`pg_try_advisory_lock` with bounded retry.

---

## Medium

- **Sync handlers + heavy work share the threadpool.** `/similar-cards` (ONNX inference, not covered
  by the 5s `statement_timeout`) and `/sitemap.xml` (full ~30k-row scan, no server-side cache) run
  in FastAPI's bounded threadpool and can starve `/health`/`/ready`. Memoize the sitemap; budget
  inference. `routers/search.py`, `routers/seo.py:44,56`.
- **`statement_timeout=5s` is set per-connection on the shared engine** (`core/database.py:74-86`);
  if the API ever migrates it would kill `CREATE EXTENSION`/`create_all` DDL. Reset timeout to 0 on
  the migration connection, or migrate only from the worker.
- **`system_metadata.updated_at` is overloaded** as both a timestamp (`scryfall_data` key) and a
  state enum (`schema_migration` key) — `core/models.py:49`, `db_init.py:69-107`. Add a dedicated
  `state` column.
- **`_upsert_schema_version` is read-modify-write on `scryfall_data.updated_at`** (`db_init.py:141`),
  racing the ingest writer; can clobber a newer timestamp. Use `ON CONFLICT DO UPDATE SET version =
  excluded.version` and leave `updated_at` untouched.
- **Concurrent `materialize_semantic_model` for the same model races on `extract_dir`** (one
  `rmtree`s while another reads) — `model_registry.py:191-209`. Extract to a temp dir and
  `os.replace` atomically.
- **Index-reload polling does duplicate work under load** — `semantic/index.py:448-451` reads
  `_index`/`_last_refresh_check` outside the lock; a model swap can spawn N concurrent S3 downloads
  + ONNX sessions. Gate materialization with an in-progress flag under the lock.
- **Rate-limit semaphore in tag fetch is a no-op** — `ingest/fetch_tags.py:607-625` sizes permits ==
  worker count, so it never throttles; only the per-request sleep limits rate, and that's
  latency-dependent. Drop the semaphore or use a token bucket.
- **Failed/zero-tag cards are re-fetched every cron run forever** — `fetch_tags.py:636-665`; the
  "needs fetch" query keys off absence of any `CardTagging` row. Record a `last_tag_fetch_at` marker.
- **`cards_raw` only ever holds the best printing, not all ~300k** — `scryfall_ingestion.py:564-600`
  upserts `best_printings.values()` (~30k) while the obsolete-raw delete keeps the full
  `seen_scryfall_ids` (~300k). Confirm intent vs. the CLAUDE.md "~300k rows" claim; the delete
  keep-set should match what's actually inserted.
- **Color filters don't coalesce nullable columns** — `semantic/index.py:253-265`; a NULL
  `CardFace.colors` makes `at_most`/`exact` silently drop colorless cards. Coalesce to `[]`.
- **Bundles are fully buffered in RAM and re-parsed 5+ times** — `model_registry.py`,
  `bundle_registration.py`. Parse the zip once; stream S3 download to a temp file. OOM risk on small
  promotion hosts with large PyTorch bundles.
- **Promotion holds a DB connection (pool size 2) for the entire encode loop** —
  `model_promotion.py:113-136` keeps a server-side cursor open across minutes of ONNX compute.
  Materialize face rows up front or keyset-paginate.
- **Numeric env vars crash startup on a typo** — `core/config.py`/`core/database.py` do bare
  `int(os.getenv(...))` at import time. Wrap in a default-on-`ValueError` helper.

---

## Low (selected)

- Sitemap hard-truncates at 50k with a silent `break` — log when the cap is hit (`seo.py:44`).
- `RequestValidationError` handler mutates Pydantic's live error dicts in place (`main.py:201-207`).
- `RequestSizeLimitMiddleware` buffers full body before size check when `Content-Length` is absent
  (`main.py:84-95`).
- Add `max_length` to `card_type`/`format`/`colors`/`rarity` query params (`search.py:109-123`).
- `cleanup_unplayable_cards` rowcount `or` fallback over-reports on a legitimate 0
  (`scryfall_ingestion.py:240`).
- Non-seeded `random` in dataset sampling makes `semantic_data_version` an unreliable dataset
  identity (`dataset_service.py:149`).

---

## Doc/Design notes (not bugs)

- **CLAUDE.md says "pgvector HNSW index on embedding"; the migration explicitly ships none**
  (`0001_initial_schema.py:9-11`: "exact pgvector cosine over a small (~33k) embedding table"). Per
  active model the scan is ~33k 384-dim vectors per `/similar-cards`. Either fix the doc or add the
  index — verify measured latency under the 5s `statement_timeout`. This is a deliberate tradeoff,
  but the doc and code disagree.
- The "single atomic transaction" delete-phase claim (`scryfall_ingestion.py:605`) is accurate for
  delete+meta only; the **upsert phase commits per-batch**, so a mid-upsert crash leaves
  partially-applied data (eventually consistent on re-run). Reword the comment to scope the
  guarantee.

---

## Verified non-issues (good patterns)

- Admin JWT decode pins `algorithms=[HS256]` (no `alg=none`); Cloudflare Access pins RS256 +
  audience/issuer; admin password uses `hmac.compare_digest`.
- Oracle-pool rotation uses `asyncio.to_thread`, swallows per-iteration errors, re-raises
  `CancelledError`, and swaps via atomic reference reassignment.
- ONNX inference does not block the event loop (`/similar-cards` is a sync `def` route → threadpool).
- Embedding normalization (L2, eps 1e-12) and mean-pooling are correct; query and stored vectors are
  both normalized, so cosine distance is consistent.
- Per-thread `requests.Session` via `threading.local`; bulk download streamed in 1MB chunks; reduce
  phase uses `ijson` streaming; DB writes happen only on the main thread (workers return data).
- The embedding swap itself (`_store_model_embeddings_batches`) is genuinely atomic for the target
  model — the atomicity gap is at the orchestration level (#1), not the swap.
