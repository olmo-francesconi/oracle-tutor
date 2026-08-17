"""Score the active semantic model against held-out Scryfall tags.

Usage (from backend/):
    uv run python -m scripts.eval_tags
    uv run python -m scripts.eval_tags --prod
    uv run python -m scripts.eval_tags --store        # write into metrics_json

Unlike `eval_queries.json` (20 hand-written queries scored by face-text cosine),
this runs through the real retrieval path against ~280 queries built from tags
the model was never trained on. See semantic/tag_eval.py.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from ._common import add_prod_flag, load_env, setup_logging

logger = logging.getLogger("ot_backend.semantic.scripts.eval_tags")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_tags")
    parser.add_argument("--limit", type=int, default=100, help="Results retrieved per query (default: 100).")
    parser.add_argument(
        "--holdout-percent",
        type=int,
        default=None,
        help="Override the share of tags reserved for evaluation. Must match what the dataset was built with.",
    )
    parser.add_argument(
        "--store",
        action="store_true",
        help="Write the result into the active model's metrics_json under 'tag_eval'.",
    )
    add_prod_flag(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    load_env(prod=args.prod)
    setup_logging()

    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import SemanticModel
    from ot_backend.semantic.index import get_semantic_index
    from ot_backend.semantic.tag_eval import (
        DEFAULT_HOLDOUT_PERCENT,
        evaluate_tags,
        load_tag_eval_queries,
    )

    holdout = args.holdout_percent if args.holdout_percent is not None else DEFAULT_HOLDOUT_PERCENT
    index = get_semantic_index()
    if index is None:
        logger.error("No active semantic model — nothing to evaluate.")
        return 1

    with SessionLocal() as db:
        queries = load_tag_eval_queries(db, holdout_percent=holdout)
        if not queries:
            logger.error(
                "No eval queries. The database needs Scryfall tag data (card_taggings); "
                "a corpus without tags cannot produce a tag-derived benchmark."
            )
            return 1
        logger.info("Evaluating model %s over %d held-out queries.", index.model_id, len(queries))
        summary = evaluate_tags(index, db, queries, limit=args.limit)

        if args.store and index.model_id:
            model = db.get(SemanticModel, index.model_id)
            if model is not None:
                merged = dict(model.metrics_json or {})
                merged["tag_eval"] = summary
                model.metrics_json = merged
                db.commit()
                logger.info("Stored tag_eval in metrics_json for %s", index.model_id)

    print(json.dumps({"model_id": index.model_id, **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
