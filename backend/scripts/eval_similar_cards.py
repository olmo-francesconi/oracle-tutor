"""Score card-to-card similarity against external ground truth.

Usage (from backend/):
    uv run python -m scripts.eval_similar_cards
    uv run python -m scripts.eval_similar_cards --model post-hob-aug-local
    uv run python -m scripts.eval_similar_cards --verbose

Unlike `eval_tags`, the relationships here come from Wizards' templating and
published community lists rather than from Scryfall Tagger and phrasings we
wrote ourselves. See semantic/similar_card_eval.py.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from ._common import add_prod_flag, load_env, setup_logging

logger = logging.getLogger("ot_backend.semantic.scripts.eval_similar_cards")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_similar_cards")
    parser.add_argument("--model", default=None, help="Model slug to score (default: the active one).")
    parser.add_argument("--scan-depth", type=int, default=200, help="Results scanned per seed (default: 200).")
    parser.add_argument("--verbose", action="store_true", help="Print every pair, not just the summary.")
    add_prod_flag(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    load_env(prod=args.prod)
    setup_logging()

    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import SemanticModel
    from ot_backend.semantic.index import SemanticIndex, get_semantic_index
    from ot_backend.semantic.model_registry import materialize_semantic_model
    from ot_backend.semantic.similar_card_eval import evaluate_similar_cards

    with SessionLocal() as db:
        if args.model:
            model = db.query(SemanticModel).filter(SemanticModel.slug == args.model).one_or_none()
            if model is None:
                logger.error("No model with slug %r.", args.model)
                return 1
            model_root, _ = materialize_semantic_model(model)
            index = SemanticIndex(model_root=model_root, model_id=model.id)
        else:
            index = get_semantic_index()
            if index is None:
                logger.error("No active semantic model — nothing to evaluate.")
                return 1
        summary = evaluate_similar_cards(index, db, scan_depth=args.scan_depth)

    results = summary.pop("results")
    if args.verbose:
        for row in sorted(results, key=lambda r: (r["category"], r["rank"] or 10**6)):
            mark = "ok  " if row["passed"] else "MISS"
            rank = row["rank"] if row["rank"] is not None else f">{args.scan_depth}"
            print(f"  {mark} [{row['category']:<18}] {row['seed']:<22} -> {row['expected']:<22} rank {rank}")
        print()
    print(json.dumps({"model": args.model or "active", **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
