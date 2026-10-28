"""Score a model on held-out Scryfall tags through the real retrieval path (app.search).

Run from repo root: uv run --project train python -m train.eval --model MODEL_ID

Scores the served model (current.json's, on the live snapshot's vectors) and, with `--model`, a candidate (a bucket
model id or a local dir) whose corpus vectors are re-embedded in memory. A bucket candidate's scores are written into
its models/<id>/meta.json. Without a bucket it reads data/ and model/.

A tag name is a query a player might type and its cards are the gold set: ~1k queries for free. Queries run through
`app.search.Index.search_text`, so query segmentation, IDF and scoring are inside the measurement.
* **Tags are held out, not cards** (`train.tags.is_held_out_tag`, which train/dataset.py also applies); otherwise the
  score measures memorisation.
* **Paraphrases are scored as their own kind**: tag names are Tagger slugs, and optimising for slugs teaches slugs.
"""

import argparse
import json
import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from app import search, snapshot
from app.build import embed
from app.encoder import Encoder
from app.text import ability_text_hash
from train.dataset import load_ability_texts, load_cards
from train.tags import TAGS_PATH, is_held_out_tag, load_tags

# Smaller tags give unstable metrics; larger ones are broad categories ("activated ability") no ranking satisfies.
MIN_TAG_CARDS = 20
MAX_TAG_CARDS = 600
PARAPHRASES = Path(__file__).with_name("tag_eval_paraphrases.json")


def eval_queries(tags: dict, known: set[str]) -> list[tuple[str, str, frozenset[str]]]:
    """(kind, query, gold oracle_ids) for held-out tags only."""
    queries, gold_by_tag = [], {}
    for tag, (description, oracle_ids) in tags.items():
        gold = frozenset(oracle_ids) & known
        if not is_held_out_tag(tag) or not MIN_TAG_CARDS <= len(gold) <= MAX_TAG_CARDS:
            continue
        gold_by_tag[tag] = gold
        name = tag.replace("-", " ").replace("_", " ")
        queries.append(("name", name, gold))
        if description:
            queries.append(("described", f"{name}. {description}", gold))
    # Only paraphrases of held-out tags count; for the rest the model has trained on the answer.
    for phrase, tag in json.loads(PARAPHRASES.read_text())["paraphrases"].items():
        if tag in gold_by_tag:
            queries.append(("paraphrase", phrase, gold_by_tag[tag]))
    return queries


def metrics(ranked: list[str], gold: frozenset[str]) -> dict[str, float]:
    first = next((i for i, oid in enumerate(ranked, 1) if oid in gold), None)
    return {
        "mrr": 1.0 / first if first else 0.0,
        "p_at_10": sum(oid in gold for oid in ranked[:10]) / 10.0,
        # Capped at 100: a 400-card tag cannot fit in a 100-long list, and scoring it 0.25 would punish the tag's
        # size rather than the ranking.
        "recall_at_100": sum(oid in gold for oid in ranked[:100]) / min(len(gold), 100),
    }


def score(index: search.Index, tags: dict) -> dict:
    alive = index.mask()
    by_kind = defaultdict(list)
    for kind, query, gold in eval_queries(tags, set(index.cards)):
        hits = index.search_text(search.query_abilities(query), 100, alive)
        ranked = list(dict.fromkeys(card["oracle_id"] for card, *_ in hits))
        by_kind[kind].append(metrics(ranked, gold))

    def mean(rows: list[dict]) -> dict:
        return {"queries": len(rows), **{k: round(sum(r[k] for r in rows) / len(rows), 4) for k in rows[0]}}

    summary = {kind: mean(rows) for kind, rows in sorted(by_kind.items())}
    summary["all"] = mean([r for rows in by_kind.values() for r in rows])
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", help="candidate: bucket model id or local model dir")
    parser.add_argument("--data", type=Path, default=Path("data"), help="local data dir (no bucket only)")
    parser.add_argument("--tags", type=Path, default=TAGS_PATH)
    args = parser.parse_args()

    tags = load_tags(args.tags)
    cache = Path(os.environ.get("CACHE_DIR") or Path(tempfile.gettempdir()) / "oracle-tutor")
    if snapshot.enabled():
        pointer = snapshot.read_pointer()
        if not pointer:
            raise SystemExit(f"no {snapshot.POINTER} in the bucket")
        data_dir, served = snapshot.download_data(pointer["snapshot"], cache), pointer["model"]
        served_dir = snapshot.download_model(served, cache)
    else:
        data_dir, served, served_dir = args.data, "model", Path("model")
    results = {served: score(search.load(data_dir, Encoder(served_dir)), tags)}

    if args.model and args.model != served:
        local = Path(args.model).is_dir()
        model_dir = Path(args.model) if local else snapshot.download_model(args.model, cache)
        cards, _ = load_cards(data_dir / "cards.json.gz")
        texts = {ability_text_hash(t): t for t in set(load_ability_texts(cards).values())}
        hashes, vectors = embed(texts, model_dir)
        results[args.model] = score(search.Index(cards, hashes.tolist(), vectors, Encoder(model_dir)), tags)
        if not local:
            key = f"models/{args.model}/meta.json"
            meta = snapshot.read_json(key) or {}
            meta["eval"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "scores": results[args.model],
                            "served": {"model": served, "scores": results[served]}}
            snapshot.write_json(key, meta)
            print(f"wrote scores to {key}")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
