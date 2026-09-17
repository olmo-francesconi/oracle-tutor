from __future__ import annotations

import argparse
import faulthandler
import logging
import os
import sys
import threading
from typing import cast

from ..core.logging_config import setup_loggers
from .scryfall_ingestion import update_scryfall_data

logger = logging.getLogger("ot_backend.ingest")


class WorkerArgs(argparse.Namespace):
    force: bool = False
    trigger_type: str = "manual"
    strict: bool = False
    refresh_tags: bool = False
    skip_tags: bool = False
    skip_embedding_topup: bool = False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oracle-tutor-worker")
    _ = parser.add_argument(
        "--force",
        action="store_true",
        help="Force download/re-ingestion even if the system appears up to date.",
    )
    _ = parser.add_argument(
        "--trigger-type",
        default=os.getenv("OT_TRIGGER_TYPE", "manual"),
        help="Ingestion trigger type stored in ingestion logs (default: manual).",
    )
    _ = parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail fast (exit 1) on fetch/download errors instead of treating as a noop.",
    )
    _ = parser.add_argument(
        "--refresh-tags",
        action="store_true",
        help="Re-fetch tags for EVERY card. Without this, ingestion keeps existing taggings and only fetches cards that have none, which is the fast path.",
    )
    _ = parser.add_argument(
        "--skip-embedding-topup",
        action="store_true",
        help=(
            "Do not embed newly ingested ability texts with the active model. "
            "Without the top-up, cards printed with new wording stay invisible to "
            "semantic search until the next model promotion."
        ),
    )
    _ = parser.add_argument(
        "--skip-tags",
        action="store_true",
        help="Skip the Tagger phase entirely. Existing taggings are preserved.",
    )
    return parser


def main() -> int:
    """
    One-shot ingestion job, run manually on Railway or locally.

    This command runs the stale-aware Scryfall update exactly once and then exits.
    """

    setup_loggers()
    args = cast(WorkerArgs, _build_parser().parse_args())

    logger.info(
        "Oracle Tutor Worker starting (one-shot). force=%s refresh_tags=%s skip_tags=%s "
        "skip_embedding_topup=%s strict=%s trigger_type=%s",
        args.force,
        args.refresh_tags,
        args.skip_tags,
        args.skip_embedding_topup,
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
        if args.skip_embedding_topup:
            logger.info("Embedding top-up skipped by flag.")
        else:
            # Ingest writes card_face_abilities but never embeds them; only
            # promotion does, and it rewrites everything. Without this, a card
            # printed with new wording is absent from the index until someone
            # promotes a model. Cheap when nothing is missing.
            try:
                from ..semantic.model_promotion import topup_active_model_embeddings

                added = topup_active_model_embeddings()
                if added:
                    logger.info("Embedded %d new ability texts.", added)
            except Exception:
                # Never fail an otherwise good ingest over the top-up.
                logger.exception("Embedding top-up failed (non-fatal).")

        logger.info("Worker finished (updated=%s).", updated)
        # Per requirement: exit 0 even when up-to-date.
        return 0
    except Exception:
        logger.exception("Worker failed.")
        return 1


if __name__ == "__main__":
    code = main()
    # Diagnostic: the container has stayed alive for days after "Worker finished".
    # List what is still running, and if the process is still here a minute later,
    # dump every thread's stack to stderr to show what shutdown is blocked on.
    logger.info(
        "Threads alive at exit: %s",
        [(t.name, "daemon" if t.daemon else "non-daemon") for t in threading.enumerate()],
    )
    faulthandler.dump_traceback_later(60)
    sys.exit(code)
