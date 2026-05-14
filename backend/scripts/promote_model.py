"""Promote a registered semantic model to active status.

Usage (from backend/):
    uv run python -m scripts.promote_model --model-id <uuid>
    uv run python -m scripts.promote_model --model-id <uuid> --embed-batch-size 128
    uv run python -m scripts.promote_model --model-id <uuid> --prod
"""
from __future__ import annotations

import argparse
import logging
import sys

from ._common import add_prod_flag, load_env, setup_logging

logger = logging.getLogger("ot_backend.semantic.scripts.promote_model")

_DEFAULT_EMBED_BATCH_SIZE = 64


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.promote_model")
    parser.add_argument("--model-id", required=True, help="UUID of the semantic model to promote.")
    parser.add_argument(
        "--embed-batch-size",
        type=int,
        default=_DEFAULT_EMBED_BATCH_SIZE,
        help=f"Embedding batch size (default: {_DEFAULT_EMBED_BATCH_SIZE}).",
    )
    add_prod_flag(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    load_env(prod=args.prod)
    setup_logging()

    from ot_backend.semantic.model_promotion import promote_semantic_model

    logger.info("Promoting semantic model. id=%s embed_batch_size=%d", args.model_id, args.embed_batch_size)
    success = promote_semantic_model(args.model_id, embed_batch_size=args.embed_batch_size)
    if not success:
        logger.error("Model promotion failed. id=%s", args.model_id)
        return 1
    logger.info("Model promotion complete. id=%s", args.model_id)
    print(f"model_id={args.model_id} status=active")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
