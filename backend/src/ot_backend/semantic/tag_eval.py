"""Tag-derived retrieval evaluation.

The hand-written `eval_queries.json` set is 20 queries scored by cosine over
face text — a system we do not ship. It cannot separate two models: the last
three scored 0.197 / 0.211 / 0.205, which is noise.

This harness instead uses the Scryfall Tagger data already in the database as a
relevance benchmark: a tag name is a query a player might type, and the cards
carrying that tag are the ground truth. That yields ~1,100 usable queries for
free, and it runs them through `SemanticIndex.search_oracle`, so candidate
generation, filters and IDF weighting are all inside the measurement.

Two rules make the number trustworthy:

* **Tags are held out, not cards.** A tag is either wholly in the training data
  or wholly in the test set, decided by a hash of its name so the split is
  stable and needs no stored state. `dataset_service` applies the same
  predicate. Without this we would be scoring memorisation.
* **Paraphrases are scored separately.** Tag names are Tagger slugs
  ("gains pp counters"), not what people type. Optimising for slugs would teach
  the model slugs. `tag_eval_paraphrases.json` maps natural phrasings onto tags
  and is reported as its own number.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from .index import SemanticIndex

logger = logging.getLogger("ot_backend.semantic.tag_eval")

# Tags smaller than this give unstable metrics; larger ones are broad
# categories ("activated ability") that no ranking can satisfy, and they run
# into the retrieval ceiling described in `evaluate_tags`.
DEFAULT_MIN_TAG_CARDS = 20
DEFAULT_MAX_TAG_CARDS = 600
# Share of eligible tags reserved for evaluation and excluded from training.
DEFAULT_HOLDOUT_PERCENT = 15
_HOLDOUT_SALT = "ot-tag-holdout-v1"


def is_held_out_tag(tag_name: str, *, holdout_percent: int = DEFAULT_HOLDOUT_PERCENT) -> bool:
    """Whether a tag belongs to the eval split.

    Hash-based rather than a stored sample: the same tag always lands on the
    same side, no state to keep in sync between the trainer and the evaluator,
    and adding tags never reshuffles the existing split.
    """
    if holdout_percent <= 0:
        return False
    digest = hashlib.sha256(f"{_HOLDOUT_SALT}:{tag_name}".encode()).digest()
    return (int.from_bytes(digest[:4], "big") % 100) < holdout_percent


@dataclass(frozen=True)
class TagEvalQuery:
    query: str
    kind: str  # "name" | "described" | "paraphrase"
    tag_name: str
    gold_oracle_ids: frozenset[str]


def _tag_rows(db: Session, *, min_cards: int, max_cards: int) -> list[tuple[str, str | None, list[str]]]:
    from sqlalchemy import func, select

    from ..core.models import CardTagging, Tag

    counts = (
        select(Tag.tag_name, func.count().label("n"))
        .join(CardTagging, CardTagging.tag_id == Tag.id)
        .where(CardTagging.foreign_key == "oracleId", Tag.tag_namespace == "card")
        .group_by(Tag.tag_name)
        .having(func.count().between(min_cards, max_cards))
        .subquery()
    )
    rows = db.execute(
        select(Tag.tag_name, Tag.tag_description, CardTagging.card_id)
        .join(CardTagging, CardTagging.tag_id == Tag.id)
        .join(counts, counts.c.tag_name == Tag.tag_name)
        .where(CardTagging.foreign_key == "oracleId", Tag.tag_namespace == "card")
    ).all()

    grouped: dict[str, tuple[str | None, list[str]]] = {}
    for tag_name, description, card_id in rows:
        entry = grouped.setdefault(tag_name, (description, []))
        entry[1].append(card_id)
    return [(name, desc, ids) for name, (desc, ids) in grouped.items()]


def load_tag_eval_queries(
    db: Session,
    *,
    holdout_percent: int = DEFAULT_HOLDOUT_PERCENT,
    min_cards: int = DEFAULT_MIN_TAG_CARDS,
    max_cards: int = DEFAULT_MAX_TAG_CARDS,
    include_paraphrases: bool = True,
) -> list[TagEvalQuery]:
    """Build the eval set from held-out tags only."""
    queries: list[TagEvalQuery] = []
    gold_by_tag: dict[str, frozenset[str]] = {}

    for tag_name, description, card_ids in _tag_rows(db, min_cards=min_cards, max_cards=max_cards):
        if not is_held_out_tag(tag_name, holdout_percent=holdout_percent):
            continue
        gold = frozenset(card_ids)
        gold_by_tag[tag_name] = gold
        readable = tag_name.replace("-", " ").replace("_", " ")
        queries.append(TagEvalQuery(readable, "name", tag_name, gold))
        if description:
            queries.append(TagEvalQuery(f"{readable}. {description}", "described", tag_name, gold))

    if include_paraphrases:
        for phrase, tag_name in load_paraphrases().items():
            gold = gold_by_tag.get(tag_name)
            if gold is None:
                # Only score paraphrases whose tag is in the held-out split;
                # otherwise the model has trained on the answer.
                continue
            queries.append(TagEvalQuery(phrase, "paraphrase", tag_name, gold))

    return queries


def load_paraphrases() -> dict[str, str]:
    raw = files("ot_backend.semantic").joinpath("tag_eval_paraphrases.json").read_bytes()
    payload: dict[str, Any] = json.loads(raw)
    return {str(k): str(v) for k, v in payload.get("paraphrases", {}).items()}


def _metrics_for(ranked_oracle_ids: list[str], gold: frozenset[str]) -> dict[str, float]:
    reciprocal_rank = 0.0
    for position, oracle_id in enumerate(ranked_oracle_ids, start=1):
        if oracle_id in gold:
            reciprocal_rank = 1.0 / position
            break
    top10 = ranked_oracle_ids[:10]
    top100 = ranked_oracle_ids[:100]
    hits100 = sum(1 for oracle_id in top100 if oracle_id in gold)
    # Denominator is capped at 100: a tag with 400 members cannot have all of
    # them inside a 100-long list, and scoring it as 0.25 would punish the model
    # for the size of the tag rather than the quality of the ranking.
    return {
        "mrr": reciprocal_rank,
        "p_at_10": sum(1 for oracle_id in top10 if oracle_id in gold) / 10.0,
        "recall_at_100": hits100 / min(len(gold), 100),
    }


def evaluate_tags(
    index: SemanticIndex,
    db: Session,
    queries: list[TagEvalQuery],
    *,
    limit: int = 100,
) -> dict[str, Any]:
    """Score `queries` through the real retrieval path.

    NOTE on the ceiling: `index._CANDIDATE_FACES_PER_ABILITY` bounds how many
    faces a single-ability query can ever return. A tag larger than that bound
    cannot reach recall 1.0 no matter how good the model is, which is why
    `DEFAULT_MAX_TAG_CARDS` keeps the eval set below it.
    """
    per_kind: dict[str, list[dict[str, float]]] = {}
    for evaluated, query in enumerate(queries, start=1):
        hits = index.search_oracle(query.query, limit=limit, db=db)
        seen: set[str] = set()
        ranked: list[str] = []
        for hit in hits:
            oracle_id = hit.face_key[0]
            if oracle_id not in seen:
                seen.add(oracle_id)
                ranked.append(oracle_id)
        per_kind.setdefault(query.kind, []).append(_metrics_for(ranked, query.gold_oracle_ids))
        if evaluated % 100 == 0:
            logger.info("Tag eval progress %d/%d", evaluated, len(queries))

    def _mean(rows: list[dict[str, float]], key: str) -> float:
        return round(sum(row[key] for row in rows) / len(rows), 4) if rows else 0.0

    summary: dict[str, Any] = {"query_count": len(queries), "by_kind": {}}
    everything = [row for rows in per_kind.values() for row in rows]
    for kind, rows in sorted(per_kind.items()):
        summary["by_kind"][kind] = {
            "query_count": len(rows),
            "mrr": _mean(rows, "mrr"),
            "p_at_10": _mean(rows, "p_at_10"),
            "recall_at_100": _mean(rows, "recall_at_100"),
        }
    summary["mrr"] = _mean(everything, "mrr")
    summary["p_at_10"] = _mean(everything, "p_at_10")
    summary["recall_at_100"] = _mean(everything, "recall_at_100")
    return summary
