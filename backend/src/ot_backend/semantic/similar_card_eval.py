"""Card-to-card similarity benchmark built on external ground truth.

The tag benchmark (`tag_eval`) measures us against Scryfall Tagger's coverage
using queries phrased as Tagger slugs, and its paraphrases were written by us —
so it scores our own guesses about phrasing as much as it scores retrieval. This
one has neither problem. The relationships come from Wizards' own templating
(functional reprints, printed cycles) or from published community swap lists,
and the task is the one the product performs: given this card, show me cards
like it.

It is a regression test, not a leaderboard: the pass mark is a rank threshold
per category, because a functional reprint sharing near-identical text should be
in the top few, while a budget swap is a judgement call that only needs to place.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from .index import SemanticIndex

logger = logging.getLogger("ot_backend.semantic.similar_card_eval")

# How near the top a relationship of each kind is expected to land. Identical
# text has no excuse; a community swap recommendation is a looser claim.
RANK_TARGETS = {
    "functional_reprint": 5,
    "cycle": 10,
    "near_equivalent": 20,
    "budget_swap": 50,
}
DEFAULT_SCAN_DEPTH = 200
# Scores this close are the same score; see the tie note in evaluate_similar_cards.
_TIE_EPSILON = 1e-6


@dataclass(frozen=True)
class SimilarCardCase:
    seed: str
    expect: tuple[str, ...]
    category: str


def load_reference() -> list[SimilarCardCase]:
    raw = files("ot_backend.semantic").joinpath("similar_card_reference.json").read_bytes()
    payload: dict[str, Any] = json.loads(raw)
    return [
        SimilarCardCase(str(e["seed"]), tuple(str(x) for x in e["expect"]), str(e["category"]))
        for e in payload["entries"]
    ]


def _face_of(db: Session, name: str) -> tuple[str, int] | None:
    from sqlalchemy import func, select

    from ..core.models import CardFace

    row = db.execute(
        select(CardFace.oracle_id, CardFace.face_ix)
        .where(func.lower(CardFace.name) == name.lower())
        .order_by(CardFace.face_ix)
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def evaluate_similar_cards(
    index: SemanticIndex,
    db: Session,
    cases: list[SimilarCardCase] | None = None,
    *,
    scan_depth: int = DEFAULT_SCAN_DEPTH,
) -> dict[str, Any]:
    """Rank each expected card in its seed's similarity results."""
    from ..core.models import CardFace

    cases = cases if cases is not None else load_reference()
    results: list[dict[str, Any]] = []
    missing: list[str] = []

    for case in cases:
        seed_face = _face_of(db, case.seed)
        if seed_face is None:
            missing.append(case.seed)
            continue
        hits = index.similar_to_face(seed_face, scan_depth, db)
        best_score = hits[0].score if hits else 0.0
        ranked = {}
        for position, hit in enumerate(hits, start=1):
            name = db.get(CardFace, {"oracle_id": hit.face_key[0], "face_ix": hit.face_key[1]})
            if name is not None and name.name not in ranked:
                ranked[name.name] = (position, hit.score)

        for wanted in case.expect:
            if _face_of(db, wanted) is None:
                missing.append(wanted)
                continue
            rank, score = ranked.get(wanted, (None, None))
            # A card whose text is identical to the seed's scores identically, and
            # ordering within that tied block is arbitrary — 366 vanilla faces share
            # one placeholder text. Judging such a pair by ordinal rank measures the
            # tiebreak, not the retrieval.
            tied = score is not None and score >= best_score - _TIE_EPSILON
            results.append({
                "seed": case.seed, "expected": wanted, "category": case.category,
                "rank": rank, "score": score, "tied_at_top": tied,
                "passed": tied or (rank is not None and rank <= RANK_TARGETS.get(case.category, 50)),
            })

    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({r["category"] for r in results}):
        rows = [r for r in results if r["category"] == category]
        found = [r for r in rows if r["rank"] is not None]
        by_category[category] = {
            "pairs": len(rows),
            "passed": sum(1 for r in rows if r["passed"]),
            "target_rank": RANK_TARGETS.get(category),
            "median_rank": sorted(r["rank"] for r in found)[len(found) // 2] if found else None,
            "tied_at_top": sum(1 for r in rows if r["tied_at_top"]),
            "not_found": len(rows) - len(found),
        }

    summary = {
        "pairs": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "pass_rate": round(sum(1 for r in results if r["passed"]) / len(results), 4) if results else 0.0,
        "by_category": by_category,
        "results": results,
    }
    if missing:
        # Loudly, not silently: a benchmark that quietly skips half its cases
        # reports a pass rate for a set nobody chose.
        summary["missing_from_corpus"] = sorted(set(missing))
        logger.warning("Cards absent from the corpus: %s", sorted(set(missing)))
    return summary
