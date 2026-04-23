from __future__ import annotations

import argparse
import logging
import sys
import threading
from contextlib import contextmanager
from typing import Iterator

from ..core.config import (
    semantic_job_heartbeat_seconds,
    semantic_job_stale_seconds,
    semantic_promote_max_jobs_per_run,
)
from ..core.database import SessionLocal
from ..core.db_init import INIT_MODE_WORKER, init_db
from ..core.logging_config import setup_loggers
from .model_promotion import begin_semantic_model_promotion, run_semantic_model_promotion
from .semantic_jobs import (
    SEMANTIC_JOB_TYPE_PROMOTE,
    claim_next_semantic_job,
    fail_stale_running_jobs,
    get_semantic_job,
    mark_semantic_job_failed,
    mark_semantic_job_succeeded,
    parse_promote_job_payload,
    touch_semantic_job_heartbeat,
)

logger = logging.getLogger("ot_backend.semantic.promote_worker")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ot_backend.semantic.promote_worker")
    parser.add_argument("--job-id", type=str, help="Specific semantic promote job ID to execute.")
    return parser


@contextmanager
def _job_heartbeat(job_id: str, *, interval_seconds: float) -> Iterator[None]:
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(max(interval_seconds, 0.1)):
            if not touch_semantic_job_heartbeat(job_id):
                logger.warning("Stopping promote job heartbeat; job is no longer running. id=%s", job_id)
                return

    thread = threading.Thread(target=heartbeat_loop, name=f"semantic-promote-heartbeat-{job_id}", daemon=True)
    if interval_seconds > 0:
        thread.start()
    try:
        yield
    finally:
        stop_event.set()
        if thread.is_alive():
            thread.join(timeout=1.0)


def _run_claimed_promote_job(job_id: str) -> bool:
    model_id: str | None = None
    try:
        with SessionLocal() as db:
            job = get_semantic_job(db, job_id)
            if job is None:
                raise KeyError(f"Semantic job {job_id} not found.")
            payload = parse_promote_job_payload(job.payload_json)

        model_id = payload.model_id
        model = begin_semantic_model_promotion(model_id)
        logger.info("Running semantic model promotion worker. id=%s slug=%s", model.id, model.slug)
        success = run_semantic_model_promotion(model_id, embed_batch_size=payload.embed_batch_size)
        if not success:
            raise RuntimeError(f"Semantic model promotion failed for model {model_id}.")
        mark_semantic_job_succeeded(
            job_id,
            model_id=model_id,
            result_json={"model_id": model_id, "final_status": "active"},
        )
        logger.info("Semantic model promotion finished. id=%s", model_id)
        return True
    except Exception as exc:
        logger.exception("Semantic promote job failed. id=%s", job_id)
        try:
            mark_semantic_job_failed(job_id, error_message=str(exc), model_id=model_id)
        except Exception:
            logger.exception("Failed to mark semantic promote job as failed. id=%s", job_id)
        return False


def main(argv: list[str] | None = None) -> int:
    setup_loggers()
    init_db(mode=INIT_MODE_WORKER)
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])

    max_jobs = 1 if args.job_id is not None else max(semantic_promote_max_jobs_per_run(), 1)
    heartbeat_seconds = semantic_job_heartbeat_seconds()
    stale_seconds = semantic_job_stale_seconds()
    processed = 0
    had_failures = False

    while processed < max_jobs:
        stale_job_ids = fail_stale_running_jobs(job_type=SEMANTIC_JOB_TYPE_PROMOTE, stale_after_seconds=stale_seconds)
        if stale_job_ids:
            logger.warning("Marked stale semantic promote jobs as failed. ids=%s", stale_job_ids)
            had_failures = True

        try:
            job = claim_next_semantic_job(
                SEMANTIC_JOB_TYPE_PROMOTE,
                job_id=args.job_id if processed == 0 else None,
            )
        except Exception:
            logger.exception("Failed to claim semantic promote job.")
            return 1

        if job is None:
            break

        processed += 1
        logger.info("Running semantic promote job. id=%s", job.id)
        with _job_heartbeat(job.id, interval_seconds=heartbeat_seconds):
            job_succeeded = _run_claimed_promote_job(job.id)
        if not job_succeeded:
            had_failures = True

        if args.job_id is not None:
            break

    if processed == 0:
        logger.info("No pending semantic promote jobs found.")

    return 1 if had_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
