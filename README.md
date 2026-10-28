# Oracle Tutor

Semantic search for Magic: The Gathering cards: find cards by what they *do*, not just their name.

One FastAPI process serves a React SPA and an in-memory index of every card's abilities, embedded with a fine-tuned
MiniLM (ONNX Runtime, CPU). No database: a refresh worker builds card data + vectors from Scryfall into a bucket, and
the web service loads whatever snapshot the bucket points at, swapping new ones in without a restart.

## How it works

```
                 Railway bucket
                 ├── models/<model_id>/        onnx model + tokenizer
refresh worker ─►├── snapshots/<id>/           cards.json.gz + vectors.npz
(daily cron)     ├── current.json  ◄────────── web service polls, downloads, swaps in memory
                 └── model.json                promoted model; the worker embeds with it
```

- **Three things change independently.** Code ships as an image; the model and the card data live in the bucket.
  `current.json` names a snapshot *and* the model that embedded it, so they always swap together.
- **Refresh** (`python -m app.build --publish`): embeds with the model `model.json` names; skips if Scryfall and
  that model are unchanged; otherwise builds the cards, reuses the live snapshot's vectors for text it has seen (same
  model), embeds only new text, uploads the snapshot, then flips `current.json`. A failed run never touches the live pointer. Keeps the last 5 snapshots.
- **Web**: boots from `current.json`, then checks it every `POLL_SECONDS`; a new snapshot is built off to the side
  and swapped in with one reference assignment. In-flight requests finish on the old one.
- **Abilities, not cards, are the unit.** Oracle text is split into abilities (`app/text.py`); each distinct ability
  text is embedded once (~64k instances → ~38k vectors). Scoring (`app/search.py`) is one matmul plus an
  IDF-weighted Chamfer mean per face; `//` in a query separates abilities (AND semantics).

## Local development

Without a bucket the app reads `data/` and `model/` directly:

```bash
uv sync
uv run python -m app.build                    # downloads Scryfall, embeds with model/ (~6 min) → data/
uv run uvicorn app.main:app --reload          # API on :8000
cd frontend && npm install && npm run dev     # SPA on :5173, proxies /api to :8000
```

`model/` is a sentence-transformers ONNX export (`onnx/model.onnx`, `tokenizer.json`, `sentence_bert_config.json`).
Checks: `uv run ruff check . && uv run basedpyright && uv run pytest -q`; frontend: `npm run lint && npm run test`.

## Training and shipping a model

Models live only in the bucket. With the bucket credentials exported (and Modal auth in `~/.modal.toml`):

```bash
uv run --project train python -m train.tags       # Scryfall oracle-tags bulk → train/tags.jsonl.gz
uv run --project train python -m train.dataset    # live snapshot + tags → train/dataset.json.gz; LLM queries for
                                                  # ability texts not yet cached are generated on Modal first
uv run --project train python -m train.train      # fine-tune on Modal (L4) → uploads models/<model_id>/
uv run --project train python -m train.eval --model <model_id>   # vs the served model; scores go to meta.json
uv run python -m app.build --promote <model_id>   # writes model.json
```

The next `refresh` run (cron, or start it from Railway) re-embeds every card with the promoted model and flips
`current.json`. Rolling back is promoting the previous id. Options: `train.dataset --augment
tag_pairs,tag_descriptions,llm_queries --llm-limit N`; `train.train --base <hf-id> --epochs --batch-size --lr --warmup
--quantize --skip-fine-tune --local --limit N`. A full run costs roughly an hour of L4 time.

## API

All under `/api`: `GET /ready`, `/search?q=` (names), `/card/{oracle_id}`, `/similar-cards` (`oracle_id` or `q`,
filters `card_type`, `colors`, `color_feature`, `match_mode`, `cmc_min`, `cmc_max`, `format`, `rarity`,
`include_abilities`, `exclude_abilities`, paging `limit`/`offset`), `/oracle-samples?n=`. Plus `/sitemap.xml`.

## Deployment (Railway)

One project; both services build this repo's root `Dockerfile` (service settings live in Railway, not in the repo):

| Service | Settings | Runs |
|---|---|---|
| `web` | healthcheck `/api/ready`, restart on failure | uvicorn; the healthcheck gates every deploy, so swaps have no downtime |
| `refresh` | start `python -m app.build --publish`, cron `0 6 * * *`, restart never | builds a snapshot if Scryfall or `model.json` changed, exits |
| bucket | Railway Bucket | `BUCKET`, `ENDPOINT`, `ACCESS_KEY_ID`, `SECRET_ACCESS_KEY`, `REGION` referenced by both services |

Environment: `production` deploys branch `production`.

Variables: `web` needs the bucket credentials and `PUBLIC_URL`; `refresh` needs the bucket credentials.
Optional: `POLL_SECONDS` (web, default 300), `CACHE_DIR`, `BUCKET_PATH_STYLE=1` for path-style buckets (older
Railway buckets, local MinIO). Rate limiting and caching are Cloudflare's job.

First deploy: run the worker once locally with the bucket credentials and `--publish --model-id <id> --model model`
(uploads the local model, promotes it, publishes) before `web` starts; `web` refuses to boot without `current.json`.

## Attribution

Card data, images, and community tags come from [Scryfall](https://scryfall.com) under their [data terms](https://scryfall.com/docs/api). Oracle Tutor is an unofficial project and is not produced, endorsed, supported, or affiliated with Scryfall or Wizards of the Coast.

Magic: The Gathering is © Wizards of the Coast LLC. All card names, text, and imagery are property of their respective owners. No challenge to copyright is intended.

## License

[GNU General Public License v3.0](LICENSE)
