from __future__ import annotations

import argparse
import logging
import sys
import threading
from contextlib import contextmanager
from importlib import import_module
from typing import Iterator

from ..core.config import (
    modal_client_configured,
    semantic_job_heartbeat_seconds,
    semantic_job_stale_seconds,
    semantic_train_max_jobs_per_run,
)
from ..core.database import SessionLocal
from ..core.db_init import INIT_MODE_WORKER, init_db
from ..core.logging_config import setup_loggers
from .bundle_registration import register_model_bundle_bytes, semantic_model_artifact_keys
from .dataset_registry import get_semantic_dataset, get_semantic_dataset_bytes
from .eval_service import default_eval_queries_bytes
from .semantic_jobs import (
    SEMANTIC_JOB_TYPE_TRAIN,
    claim_next_semantic_job,
    create_promote_job,
    fail_stale_running_jobs,
    get_semantic_job,
    mark_semantic_job_failed,
    mark_semantic_job_succeeded,
    parse_train_job_payload,
    touch_semantic_job_heartbeat,
)

logger = logging.getLogger("ot_backend.semantic.train_worker")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ot_backend.semantic.train_worker")
    parser.add_argument("--job-id", type=str, help="Specific semantic train job ID to execute.")
    return parser


def _load_modal_train_module() -> object:
    try:
        return import_module("ot_backend.semantic.modal_train")
    except Exception as exc:
        raise RuntimeError("Packaged Modal training module could not be imported.") from exc


def _run_local_base_model_export(
    *,
    dataset_bytes: bytes,
    eval_queries_bytes: bytes,
    base_model: str,
    epochs: int,
    batch_size: int,
    augmentation_mode: str,
) -> bytes:
    modal_train = _load_modal_train_module()
    train_fn = getattr(modal_train, "train", None)
    if train_fn is None or not hasattr(train_fn, "local"):
        raise RuntimeError("Packaged training module does not expose a callable train.local().")
    logger.info("Running local base model export (skip_fine_tune=True).")
    return train_fn.local(
        dataset_bytes,
        eval_queries_bytes,
        base_model,
        epochs,
        batch_size,
        augmentation_mode,
        True,
    )


def _run_modal_training(
    *,
    dataset_bytes: bytes,
    eval_queries_bytes: bytes,
    base_model: str,
    epochs: int,
    batch_size: int,
    augmentation_mode: str,
    skip_fine_tune: bool,
) -> bytes:
    if not modal_client_configured():
        raise RuntimeError("Modal client credentials are not configured. Expected MODAL_TOKEN_ID and MODAL_TOKEN_SECRET.")
    modal_train = _load_modal_train_module()
    train_fn = getattr(modal_train, "train", None)
    if train_fn is None or not hasattr(train_fn, "remote"):
        raise RuntimeError("Packaged Modal training module does not expose a callable train.remote().")
    try:
        return train_fn.remote(
            dataset_bytes,
            eval_queries_bytes,
            base_model,
            epochs,
            batch_size,
            augmentation_mode,
            skip_fine_tune,
        )
    except Exception:
        logger.exception("Modal training failed.")
        raise


@contextmanager
def _job_heartbeat(job_id: str, *, interval_seconds: float) -> Iterator[None]:
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(max(interval_seconds, 0.1)):
            if not touch_semantic_job_heartbeat(job_id):
                logger.warning("Stopping train job heartbeat; job is no longer running. id=%s", job_id)
                return

    thread = threading.Thread(target=heartbeat_loop, name=f"semantic-train-heartbeat-{job_id}", daemon=True)
    if interval_seconds > 0:
        thread.start()
    try:
        yield
    finally:
        stop_event.set()
        if thread.is_alive():
            thread.join(timeout=1.0)


def _run_claimed_train_job(job_id: str) -> bool:
    model_id: str | None = None
    partial_result: dict[str, object] | None = None
    follow_up_warning: str | None = None
    try:
        with SessionLocal() as db:
            job = get_semantic_job(db, job_id)
            if job is None:
                raise KeyError(f"Semantic job {job_id} not found.")
            payload = parse_train_job_payload(job.payload_json)
            requested_by = job.requested_by
            dataset = get_semantic_dataset(db, payload.dataset_id)
            if dataset is None:
                raise KeyError(f"Semantic dataset {payload.dataset_id} not found.")
            augmentation_mode = dataset.augmentation_mode
            dataset_slug = dataset.slug
            dataset_bytes_for_training = get_semantic_dataset_bytes(db, payload.dataset_id)

        eval_queries_bytes = default_eval_queries_bytes()
        if payload.skip_fine_tune:
            bundle_bytes = _run_local_base_model_export(
                dataset_bytes=dataset_bytes_for_training,
                eval_queries_bytes=eval_queries_bytes,
                base_model=payload.base_model,
                epochs=payload.epochs,
                batch_size=payload.batch_size,
                augmentation_mode=augmentation_mode,
            )
        else:
            bundle_bytes = _run_modal_training(
                dataset_bytes=dataset_bytes_for_training,
                eval_queries_bytes=eval_queries_bytes,
                base_model=payload.base_model,
                epochs=payload.epochs,
                batch_size=payload.batch_size,
                augmentation_mode=augmentation_mode,
                skip_fine_tune=False,
            )

        with SessionLocal() as db:
            model = register_model_bundle_bytes(
                db,
                slug=payload.model_slug,
                base_model=payload.base_model,
                embedding_dim=payload.embedding_dim,
                artifact_bundle_bytes=bundle_bytes,
                dataset_id=payload.dataset_id,
                dataset_bytes=dataset_bytes_for_training,
                source_semantic_data_version=None,
                augmentation_mode=augmentation_mode,
                config_json={"base_model_key": payload.base_model_key, "dataset_slug": dataset_slug},
                metrics_json=None,
            )
            model_id = model.id
            artifact_keys = semantic_model_artifact_keys(db, model_id)

        partial_result = {
            "model_id": model_id,
            "model_slug": payload.model_slug,
            "dataset_id": payload.dataset_id,
            "skip_fine_tune": payload.skip_fine_tune,
            "artifact_keys": artifact_keys,
        }

        if payload.promote_after_register:
            try:
                with SessionLocal() as db:
                    promote_job = create_promote_job(
                        db,
                        requested_by=requested_by,
                        model_id=model_id,
                        embed_batch_size=payload.embed_batch_size,
                    )
                partial_result["promote_job_id"] = promote_job.id
            except Exception as exc:
                follow_up_warning = str(exc)
                partial_result["promote_job_error"] = follow_up_warning
                logger.warning(
                    "Semantic train job finished but failed to enqueue follow-up promote job. id=%s model_id=%s error=%s",
                    job_id,
                    model_id,
                    follow_up_warning,
                )

        mark_semantic_job_succeeded(job_id, model_id=model_id, dataset_id=payload.dataset_id, result_json=partial_result)
        return True
    except Exception as exc:
        logger.exception("Semantic train job failed. id=%s", job_id)
        try:
            mark_semantic_job_failed(
                job_id,
                error_message=str(exc),
                model_id=model_id,
                result_json=partial_result,
            )
        except Exception:
            logger.exception("Failed to mark semantic train job as failed. id=%s", job_id)
        return False


def main(argv: list[str] | None = None) -> int:
    setup_loggers()
    init_db(mode=INIT_MODE_WORKER)
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])

    max_jobs = 1 if args.job_id is not None else max(semantic_train_max_jobs_per_run(), 1)
    heartbeat_seconds = semantic_job_heartbeat_seconds()
    stale_seconds = semantic_job_stale_seconds()
    processed = 0
    had_failures = False

    while processed < max_jobs:
        stale_job_ids = fail_stale_running_jobs(job_type=SEMANTIC_JOB_TYPE_TRAIN, stale_after_seconds=stale_seconds)
        if stale_job_ids:
            logger.warning("Marked stale semantic train jobs as failed. ids=%s", stale_job_ids)
            had_failures = True

        try:
            job = claim_next_semantic_job(
                SEMANTIC_JOB_TYPE_TRAIN,
                job_id=args.job_id if processed == 0 else None,
            )
        except Exception:
            logger.exception("Failed to claim semantic train job.")
            return 1

        if job is None:
            break

        processed += 1
        logger.info("Running semantic train job. id=%s", job.id)
        with _job_heartbeat(job.id, interval_seconds=heartbeat_seconds):
            job_succeeded = _run_claimed_train_job(job.id)
        if not job_succeeded:
            had_failures = True

        if args.job_id is not None:
            break

    if processed == 0:
        logger.info("No pending semantic train jobs found.")

    return 1 if had_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
