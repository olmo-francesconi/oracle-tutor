# Oracle Tutor

Semantic search for Magic: The Gathering cards. One FastAPI process serves the React SPA plus an in-memory index of
card abilities embedded with a fine-tuned MiniLM (ONNX Runtime). No database, no object storage, no admin.

## Tech stack

- **Serve:** Python 3.12, FastAPI, uvicorn, numpy, onnxruntime, tokenizers, uv
- **Train (offline, `train/`, own pyproject):** sentence-transformers, datasets, huggingface_hub
- **Frontend:** React 19, TypeScript, Vite 7, TailwindCSS 4, TanStack Query v5, zod
- **Infra:** one Docker image (code only), Railway (`web` + `refresh` cron + Bucket), Cloudflare in front, GitHub Actions CI

## Repo structure

```
app/
  main.py          FastAPI app: /api routes, SPA serving with per-page OG/JSON-LD head injection, sitemap, CSP headers
  search.py        In-memory Index: load data/, filter masks, Chamfer + IDF scoring, name search, homepage samples
  text.py          Oracle text → abilities: segmentation, normalization, text_hash (verbatim port of v2)
  encoder.py       ONNX sentence encoder (mean pool + L2 norm); used by build AND serve
  build.py         Scryfall bulk → cards + vectors; local (→ data/) or `--publish` (refresh worker → bucket)
  snapshot.py      Bucket layout + I/O: models/, snapshots/, current.json
train/             tags.py (oracle-tags bulk), dataset.py (attribution + hard negatives), train.py, eval.py
tests/             Pure pytest: fake encoder + tiny dataset (conftest.py), Scryfall fixture for the build
frontend/          React SPA (unchanged API contract; `npm run build` → static/ in the image)
Dockerfile         node build → python runtime; code only, same image for web and refresh
railway.json       web service: healthcheck /api/ready
railway.worker.json refresh service: start command + daily cron
```

Local dev without a bucket reads gitignored `model/` (sentence-transformers ONNX export) and `data/` (built).

## Architecture

### Data flow
`app/build.py` reads Scryfall `default-cards`, keeps playable cards, picks the best printing per oracle_id, derives
faces + `type_categories`, segments abilities with `app.text.build_face_abilities`, and embeds each **distinct**
normalized ability text with `app.encoder.Encoder`. Output:
- `cards.json.gz`: each card is exactly the `/api/card/{oracle_id}` body plus `_`-prefixed internals
  (`_color_identity`, `_keywords`; per face `_type_categories`, `_hashes`). `/card` strips `_` keys.
  `_hashes` is 1:1 with `abilities`, except faces with no rules text: `abilities: []` and one `emptyoracle` hash,
  so vanilla creatures stay retrievable.
- `vectors.npz`: sorted `hashes`, float16 `vectors`, `model`.

Code, model and data change independently. The image is code only. The bucket holds `models/<model_id>/`,
`snapshots/<id>/` and `current.json` (`{snapshot, model, scryfall}`). The refresh worker (`python -m app.build
--publish`, daily cron) skips when Scryfall and `MODEL_ID` are unchanged; otherwise it reuses the live snapshot's
vectors for known hashes (same model only), embeds new text, uploads the snapshot, and writes `current.json` LAST,
so a failed run never changes what is live. The web service boots from `current.json` and polls it every
`POLL_SECONDS`; a new snapshot is loaded in a thread and swapped with one reference assignment. The pointer names
data and model together, so corpus and query vectors always come from the same model. Without `BUCKET` set, the app
reads `DATA_DIR`/`MODEL_DIR` (local dev, tests).

### Semantic search (`app/search.py`)
Similarity is over **abilities**, not whole cards: `[card] → [face] → [oracle text] → [abilities]`.
- Splitting (`app/text.py`): newline per ability; keyword lines ("Flying, vigilance") split on `,`/`;` via Scryfall's
  keyword-ability catalog; modal `•` lines stay with their parent; keywords whose effect lives only in reminder text
  are expanded (`keyword_expansions.json`), evergreen ones are not; overload gets its "each" mode.
- Normalization is **type-aware**: `{T}` → "tap this creature" / "tap this land". Rendering it generically collapsed
  Forest and Llanowar Elves onto one vector. Changing normalization changes `text_hash` → rebuild data.
- `ability_ix` and `text_hash` must never drift silently: `ability_ix` appears in shared URLs (`inc`/`exc`).
- Scoring: one matmul over all ~37k vectors, gathered onto ~63k instances, aggregated per face with `reduceat`.
  Bidirectional Chamfer for card mode: `(forward + backward) / 2`, both **IDF-weighted** (`log1p(N/df)` over ability
  instances). Weighted by frequency rather than keyword-ness on purpose: `Enchant creature` and `{T}: Add {C}.` are as
  common as `Flying`.
- **Text queries (`q`) are forward-only** (max-pool): searching "draw a card when a creature dies" must not demote
  cards for also having flying. Seed side not IDF-weighted (the user typed each ability on purpose).
- Queries go through the **same** segmentation/normalization as the corpus. A query has no type line, so each query
  ability is encoded once per self-reference variant ("this creature", "this land", …) and scored by its best
  variant: `{T}: Add {G}.` matches both mana dorks and lands exactly.
- ` // ` separates query abilities (AND semantics). `//` was chosen on corpus evidence: 2 occurrences in 63k ability
  rows vs 60/156/23 for `;`/`|`/`&`. Max `MAX_QUERY_ABILITIES` (6), 422 beyond, never truncated. `query_abilities` is
  echoed back; the frontend has no splitter.
- `matched_ability`: abilities within 0.05 of the best match, then the most distinctive by IDF. Not shown by the
  UI. A raw argmax says "Flying" for every flier.
- Ability tuning (card mode): `include_abilities`/`exclude_abilities` (seed `ability_ix`, URL `inc`/`exc`). Exclude
  wins when both. Excluded abilities scale a candidate's score down across 0.70..0.90 cosine and drop it at 0.90:
  short ability texts have a ~0.7 similarity floor, so an unbanded penalty would shave every card. A hand-picked
  include subset switches to forward-only.
- Exact ties (every vanilla flier scores 1.0 for "flying") break by EDHREC rank; scores are rounded to 4 decimals
  first because float16 vectors leave ~1e-5 noise.
- Filters are numpy masks precomputed per face: `card_type` (one-letter codes `cisealp`), `colors` (WUBRG) with
  `color_feature` identity|colors and `match_mode` at_least|at_most|exact, `cmc_min/max`, `format` (`spmlvcu`,
  legal or restricted), `rarity` (`curm`). Codes are allowlisted in `frontend/src/lib/filters.ts` too.
- `offset` ≤ 500, `limit` ≤ 100.

### Training (`train/`)
- Tags come from Scryfall's `oracle_tags` bulk file (one ~6 MB download; v2 scraped Tagger per card for ~9h).
- Tags live on cards, abilities two layers below, so `dataset.py` attributes each tag to the ability that justifies
  it by **within-tag token lift**, kept only if it beats the runner-up by the margin (0.5; ~86% precision vs ~64% at
  0.3), and drops tags that resolve under half their multi-ability members (name/type-line tags). Deliberately
  model-free: asking the model which ability matches is how `mana dork` broke.
- Each pair carries a mined **hard negative** from a co-occurring tag ranked by association (`overlap / other tag
  size`), checked against all of the tag's texts. MNRL with `BatchSamplers.NO_DUPLICATES`.
- `eval.py`: held-out tags (hash of the tag name, same predicate as dataset) as queries scored through
  `app.search.Index`, so IDF and query handling are inside the measurement. Paraphrases scored separately.

### API (all under `/api`, same origin as the SPA)
| Route | Purpose |
|---|---|
| `GET /ready` | `{ready, model, data}`; the SPA gates search on it |
| `GET /search?q&limit&offset` | Name search: exact, prefix, substring; EDHREC tiebreak |
| `GET /card/{oracle_id}` | Card detail with faces and segmented `abilities` |
| `GET /similar-cards` | `oracle_id` (+`face_ix`) or `q`, filters, tuning, paging; `{items, has_more, query_abilities}` |
| `GET /oracle-samples?n` | `{texts, terms}` for the homepage background |
| `GET /sitemap.xml` | One URL per oracle_id (`/?card=<id>`), origin = `PUBLIC_URL` or request |

Any other path serves the SPA; `/?card=` and `/?q=` get their OG/Twitter/JSON-LD tags injected into `index.html`
for every visitor (no bot sniffing). One stdout log line per `/similar-cards` call, no client IP.

### Frontend conventions
- Server state: TanStack Query hooks in `public/use*Query.ts`; `useApiReady` polls `/api/ready`.
- URL is the source of truth (`useUrlSync`, no router): `q`, `card`, `face`, filters, `inc`/`exc`.
- UI components don't fetch directly; `src/lib/api.ts` parses every response with zod (`types/schemas.ts`; TS types
  are `z.infer`). A malformed response throws.
- 502/503/504 show the API-down overlay.
- Design system: `DESIGN.md`.

## Dev workflows

```bash
uv sync
uv run python -m app.build [--bulk path.jsonl.gz]       # → data/ (no bucket)
uv run uvicorn app.main:app --reload                     # :8000
uv run ruff check . && uv run basedpyright && uv run pytest -q
uv run --project train pytest train/tests -q
cd frontend && npm run dev | npm run lint | npm run test | npm run build
docker build -t oracle-tutor .                           # ~20s, code only
```

## Environment variables
| Variable | Default | Notes |
|---|---|---|
| `DATA_DIR` | `data` | Built data |
| `MODEL_DIR` | `model` | Sentence-transformers ONNX export |
| `STATIC_DIR` | `static` | Built SPA; not mounted if missing (dev uses Vite) |
| `PUBLIC_URL` | request origin | Canonical origin for sitemap and link previews |
| `PORT` | `8000` | Set by Railway |
| `MODEL_ID` | — | refresh: model to serve, `<hf-repo>@<revision>` or an id already in the bucket |
| `BUCKET`, `ENDPOINT`, `ACCESS_KEY_ID`, `SECRET_ACCESS_KEY`, `REGION` | — | Railway Bucket credentials (web + refresh); unset = local mode |
| `BUCKET_PATH_STYLE` | unset | `1` for path-style buckets (older Railway buckets, MinIO) |
| `POLL_SECONDS` | `300` | web: how often to check `current.json` |
| `CACHE_DIR` | `$TMPDIR/oracle-tutor` | Downloaded models and snapshots |
| `API_PROXY_TARGET` | `http://localhost:8000` | Vite dev proxy target |

## Branches and releases

- `develop`: default branch, all work lands here. `production`: Railway builds and deploys `web` + `refresh` from it.
- Versions: `pyproject.toml` and `frontend/package.json` (keep equal).
- Release: bump versions on develop, wait for CI, then
  `git checkout production && git read-tree --reset -u develop && git commit -m "vX.Y.Z" && git tag vX.Y.Z`,
  merge back with `git checkout develop && git merge --no-ff production -m "Merge tag vX.Y.Z into develop"`, push
  production (with tags) then develop. Railway deploys on the production push; card data is the worker's job.
  `read-tree` instead of `merge --squash` avoids a conflict storm against an ancient common ancestor.
- New model: `train.eval` against the served model, `train.train --push`, set `MODEL_ID=<repo>@<rev>` on `refresh`,
  run it. No code release. Rollback: set `MODEL_ID` back (vectors for the old model are re-embedded) or point
  `current.json` at an older snapshot.

## Git commits

- `type: message` subjects, types `feat`, `fix`, `docs`, `refactor`, `chore`, `test`; imperative, no trailing period
- Never add `Co-Authored-By` or any other trailer

## Pre-push secret audit

The repo is public. Before any push:

```bash
git diff origin/$(git rev-parse --abbrev-ref HEAD)...HEAD -- . ':(exclude)*.lock' ':(exclude)package-lock.json' \
  | grep -iE '(password|secret|api[_-]?key|token|bearer|authorization|private[_-]?key|aws_)=' || echo "clean"
git diff --name-only origin/$(git rev-parse --abbrev-ref HEAD)...HEAD \
  | grep -iE '(^|/)(\.env($|\..+)|credentials|secrets|.*\.pem$|.*\.key$)' || echo "clean"
```

Secrets that must never be committed: `HF_TOKEN`, bucket `ACCESS_KEY_ID` / `SECRET_ACCESS_KEY`. If one leaks, rotate it and rewrite history.
