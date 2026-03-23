from __future__ import annotations

import argparse
import logging
import sys
from importlib import import_module

from ..core.logging_config import setup_loggers
from . import compute, train

setup_loggers()
logger = logging.getLogger("ot_backend.embed")


def _semantic_device() -> str:
    try:
        torch = import_module("torch")
    except Exception:
        return "cpu"

    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if mps is not None and getattr(mps, "is_available", lambda: False)():
        return "mps"
    return "cpu"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oracle-tutor-embed-worker")
    parser.add_argument(
        "--no-train",
        action="store_true",
        help="Skip semantic training and only recompute embeddings.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv if argv is not None else [])
    logger.info("Semantic worker starting. device=%s", _semantic_device())

    try:
        if args.no_train:
            logger.info("Semantic worker skipping training stage due to --no-train.")
        else:
            logger.info("Semantic worker entering training stage.")
            train_exit_code = train.main()
            if train_exit_code != 0:
                logger.error("Semantic worker training stage failed with exit_code=%d.", train_exit_code)
                return train_exit_code
            logger.info("Semantic worker training stage finished successfully.")

        logger.info("Semantic worker entering embedding computation stage.")
        compute_exit_code = compute.main()
        if compute_exit_code != 0:
            logger.error("Semantic worker embedding computation stage failed with exit_code=%d.", compute_exit_code)
            return compute_exit_code
        logger.info("Semantic worker embedding computation stage finished successfully.")
    except Exception:
        logger.exception("Semantic worker failed.")
        return 1

    logger.info("Semantic worker finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
