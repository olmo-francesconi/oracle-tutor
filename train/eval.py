"""Score a model on held-out Scryfall tags through the real retrieval path (app.search).

Run from repo root: uv run --project train python -m train.eval [--model DIR]

A tag name is a query a player might type and its cards are the gold set: ~1k queries for free. Queries run through
`app.search.Index.search_text`, so query segmentation, IDF and scoring are inside the measurement.
* **Tags are held out, not cards** (`train.tags.is_held_out_tag`, which train/dataset.py also applies); otherwise the
  score measures memorisation.
* **Paraphrases are scored as their own kind**: tag names are Tagger slugs, and optimising for slugs teaches slugs.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from app import search
from app.encoder import Encoder
from app.text import ability_text_hash
from app.build import embed
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--model", type=Path, help="model dir to score; re-embeds the corpus in memory "
                                                    "(default: the served model/ + data/vectors.npz)")
    parser.add_argument("--tags", type=Path, default=TAGS_PATH)
    args = parser.parse_args()

    if args.model:
        cards = load_cards(args.data / "cards.json.gz")
        texts = {ability_text_hash(t): t for t in set(load_ability_texts(cards).values())}
        hashes, vectors = embed(texts, args.model)
        index = search.Index(cards, hashes.tolist(), vectors, Encoder(args.model))
    else:
        index = search.load(args.data, Encoder(Path("model")))

    queries = eval_queries(load_tags(args.tags), set(index.cards))
    alive = index.mask()
    by_kind = defaultdict(list)
    for kind, query, gold in queries:
        hits = index.search_text(search.query_abilities(query), 100, alive)
        ranked = list(dict.fromkeys(card["oracle_id"] for card, *_ in hits))
        by_kind[kind].append(metrics(ranked, gold))

    def mean(rows: list[dict]) -> dict:
        return {"queries": len(rows), **{k: round(sum(r[k] for r in rows) / len(rows), 4) for k in rows[0]}}

    summary = {kind: mean(rows) for kind, rows in sorted(by_kind.items())}
    summary["all"] = mean([r for rows in by_kind.values() for r in rows])
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
