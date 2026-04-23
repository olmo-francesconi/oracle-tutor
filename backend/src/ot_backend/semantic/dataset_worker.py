from __future__ import annotations

import argparse
import logging
import sys
import threading
from contextlib import contextmanager
from importlib import import_module
from typing import Iterator

from sqlalchemy.exc import IntegrityError

from ..core.config import (
    modal_client_configured,
    semantic_job_heartbeat_seconds,
    semantic_job_stale_seconds,
    semantic_llm_max_faces,
    semantic_llm_max_queries_per_face,
    semantic_llm_max_tokens,
    semantic_llm_min_template_coverage,
    semantic_llm_model_name,
    semantic_llm_temperature,
    semantic_max_jobs_per_run,
)
from ..core.database import SessionLocal
from ..core.db_init import INIT_MODE_WORKER, init_db
from ..core.logging_config import setup_loggers
from .dataset_registry import create_semantic_dataset, semantic_dataset_artifact_keys, semantic_dataset_summary_metrics
from .dataset_service import export_training_build_payload_bytes, export_training_dataset_bytes
from .semantic_jobs import (
    SEMANTIC_JOB_TYPE_DATASET,
    claim_next_semantic_job,
    fail_stale_running_jobs,
    get_semantic_job,
    mark_semantic_job_failed,
    mark_semantic_job_succeeded,
    parse_dataset_job_payload,
    touch_semantic_job_heartbeat,
)
from .train_options import TRAIN_AUGMENTATION_LLM_QUERIES, parse_train_augmentation_mode

logger = logging.getLogger("ot_backend.semantic.dataset_worker")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ot_backend.semantic.dataset_worker")
    parser.add_argument("--job-id", type=str, help="Specific semantic dataset job ID to execute.")
    return parser


def _load_modal_train_module() -> object:
    try:
        return import_module("ot_backend.semantic.modal_train")
    except Exception as exc:
        raise RuntimeError("Packaged Modal training module could not be imported.") from exc


def _run_modal_dataset_build(*, training_payload_bytes: bytes, augmentation_mode: str) -> bytes:
    modal_train = _load_modal_train_module()
    build_fn = getattr(modal_train, "build_dataset", None)
    if build_fn is None or not hasattr(build_fn, "remote"):
        raise RuntimeError("Packaged Modal training module does not expose a callable build_dataset.remote().")
    if not modal_client_configured():
        raise RuntimeError("Modal client credentials are not configured. Expected MODAL_TOKEN_ID and MODAL_TOKEN_SECRET.")
    llm_config = {
        "model_name": semantic_llm_model_name(),
        "max_queries_per_face": semantic_llm_max_queries_per_face(),
        "max_faces": semantic_llm_max_faces(),
        "min_template_coverage": semantic_llm_min_template_coverage(),
        "temperature": semantic_llm_temperature(),
        "max_tokens": semantic_llm_max_tokens(),
    }
    return build_fn.remote(training_payload_bytes, augmentation_mode, llm_config)


@contextmanager
def _job_heartbeat(job_id: str, *, interval_seconds: float) -> Iterator[None]:
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(max(interval_seconds, 0.1)):
            if not touch_semantic_job_heartbeat(job_id):
                logger.warning("Stopping dataset job heartbeat; job is no longer running. id=%s", job_id)
                return

    thread = threading.Thread(target=heartbeat_loop, name=f"semantic-dataset-heartbeat-{job_id}", daemon=True)
    if interval_seconds > 0:
        thread.start()
    try:
        yield
    finally:
        stop_event.set()
        if thread.is_alive():
            thread.join(timeout=1.0)


def _run_claimed_dataset_job(job_id: str) -> bool:
    dataset_id: str | None = None
    partial_result: dict[str, object] | None = None
    try:
        with SessionLocal() as db:
            job = get_semantic_job(db, job_id)
            if job is None:
                raise KeyError(f"Semantic job {job_id} not found.")
            payload = parse_dataset_job_payload(job.payload_json)

        selected_augmentations = set(parse_train_augmentation_mode(payload.augmentation_mode))
        if TRAIN_AUGMENTATION_LLM_QUERIES in selected_augmentations:
            training_payload_bytes = export_training_build_payload_bytes(augmentation_mode=payload.augmentation_mode)
            dataset_bytes = _run_modal_dataset_build(
                training_payload_bytes=training_payload_bytes,
                augmentation_mode=payload.augmentation_mode,
            )
        else:
            dataset_bytes = export_training_dataset_bytes(augmentation_mode=payload.augmentation_mode)

        with SessionLocal() as db:
            dataset = create_semantic_dataset(
                db,
                slug=payload.dataset_slug,
                augmentation_mode=payload.augmentation_mode,
                dataset_bytes=dataset_bytes,
                metrics_json=semantic_dataset_summary_metrics(dataset_bytes),
            )
            dataset_id = dataset.id
            artifact_keys = semantic_dataset_artifact_keys(db, dataset_id)

        partial_result = {
            "dataset_id": dataset_id,
            "dataset_slug": payload.dataset_slug,
            "artifact_keys": artifact_keys,
        }
        mark_semantic_job_succeeded(job_id, dataset_id=dataset_id, result_json=partial_result)
        return True
    except IntegrityError as exc:
        logger.exception("Semantic dataset job failed on slug conflict. id=%s", job_id)
        mark_semantic_job_failed(job_id, error_message=str(exc), dataset_id=dataset_id, result_json=partial_result)
        return False
    except Exception as exc:
        logger.exception("Semantic dataset job failed. id=%s", job_id)
        try:
            mark_semantic_job_failed(job_id, error_message=str(exc), dataset_id=dataset_id, result_json=partial_result)
        except Exception:
            logger.exception("Failed to mark semantic dataset job as failed. id=%s", job_id)
        return False


def main(argv: list[str] | None = None) -> int:
    setup_loggers()
    init_db(mode=INIT_MODE_WORKER)
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])

    max_jobs = 1 if args.job_id is not None else max(semantic_max_jobs_per_run(), 1)
    heartbeat_seconds = semantic_job_heartbeat_seconds()
    stale_seconds = semantic_job_stale_seconds()
    processed = 0
    had_failures = False

    while processed < max_jobs:
        stale_job_ids = fail_stale_running_jobs(job_type=SEMANTIC_JOB_TYPE_DATASET, stale_after_seconds=stale_seconds)
        if stale_job_ids:
            logger.warning("Marked stale semantic dataset jobs as failed. ids=%s", stale_job_ids)
            had_failures = True

        try:
            job = claim_next_semantic_job(
                SEMANTIC_JOB_TYPE_DATASET,
                job_id=args.job_id if processed == 0 else None,
            )
        except Exception:
            logger.exception("Failed to claim semantic dataset job.")
            return 1

        if job is None:
            break

        processed += 1
        logger.info("Running semantic dataset job. id=%s", job.id)
        with _job_heartbeat(job.id, interval_seconds=heartbeat_seconds):
            job_succeeded = _run_claimed_dataset_job(job.id)
        if not job_succeeded:
            had_failures = True

        if args.job_id is not None:
            break

    if processed == 0:
        logger.info("No pending semantic dataset jobs found.")

    return 1 if had_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
