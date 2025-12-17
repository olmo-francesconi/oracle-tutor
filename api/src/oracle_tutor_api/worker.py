from __future__ import annotations

import argparse
import logging
import os
import sys

from .data_builder import update_scryfall_data
from .logging_config import setup_loggers

setup_loggers()
logger = logging.getLogger("oracle_tutor_api.worker")

def main() -> int:
    """
    One-shot ingestion job intended for Railway Cron (or manual invocation).

    This command runs the stale-aware Scryfall update exactly once and then exits.
    """

    parser = argparse.ArgumentParser(prog="oracle-tutor-worker")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force download/re-ingestion even if the system appears up to date.",
    )
    parser.add_argument(
        "--trigger-type",
        default=os.getenv("ORACLE_TUTOR_API_TRIGGER_TYPE", "cron"),
        help="Ingestion trigger type stored in ingestion logs (default: cron).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail fast (exit 1) on fetch/download errors instead of treating as a noop.",
    )

    args = parser.parse_args()

    logger.info(
        "Oracle Tutor Worker starting (one-shot). force=%s strict=%s trigger_type=%s",
        args.force,
        args.strict,
        args.trigger_type,
    )

    try:
        updated = update_scryfall_data(force=args.force, trigger_type=str(args.trigger_type), strict=args.strict)
        logger.info("Worker finished (updated=%s).", updated)
        # Per requirement: exit 0 even when up-to-date.
        return 0
    except Exception:
        logger.exception("Worker failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())


