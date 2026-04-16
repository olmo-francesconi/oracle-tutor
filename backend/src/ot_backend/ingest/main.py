from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import cast

from ..core.logging_config import setup_loggers
from .scryfall_ingestion import update_scryfall_data

logger = logging.getLogger("ot_backend.ingest")


class WorkerArgs(argparse.Namespace):
    force: bool = False
    trigger_type: str = "cron"
    strict: bool = False
    refresh_tags: bool = False
    skip_tags: bool = False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oracle-tutor-worker")
    _ = parser.add_argument(
        "--force",
        action="store_true",
        help="Force download/re-ingestion even if the system appears up to date.",
    )
    _ = parser.add_argument(
        "--trigger-type",
        default=os.getenv("OT_TRIGGER_TYPE", "cron"),
        help="Ingestion trigger type stored in ingestion logs (default: cron).",
    )
    _ = parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail fast (exit 1) on fetch/download errors instead of treating as a noop.",
    )
    _ = parser.add_argument(
        "--refresh-tags",
        action="store_true",
        help="Force a full Tagger refresh for all cards after ingestion.",
    )
    _ = parser.add_argument(
        "--skip-tags",
        action="store_true",
        help="Skip tag ingestion entirely (useful when you only want card data loaded).",
    )
    return parser


def main() -> int:
    """
    One-shot ingestion job intended for Railway Cron (or manual invocation).

    This command runs the stale-aware Scryfall update exactly once and then exits.
    """

    setup_loggers()
    args = cast(WorkerArgs, _build_parser().parse_args())

    logger.info(
        "Oracle Tutor Worker starting (one-shot). force=%s refresh_tags=%s skip_tags=%s strict=%s trigger_type=%s",
        args.force,
        args.refresh_tags,
        args.skip_tags,
        args.strict,
        args.trigger_type,
    )

    try:
        updated = update_scryfall_data(
            force=args.force,
            refresh_tags=args.refresh_tags,
            skip_tags=args.skip_tags,
            trigger_type=str(args.trigger_type),
            strict=args.strict,
        )
        logger.info("Worker finished (updated=%s).", updated)
        # Per requirement: exit 0 even when up-to-date.
        return 0
    except Exception:
        logger.exception("Worker failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
