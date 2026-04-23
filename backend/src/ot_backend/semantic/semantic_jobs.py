from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..core.models import SemanticDataset, SemanticJob, SemanticModel, SemanticModelEmbedding

SEMANTIC_JOB_TYPE_DATASET = "dataset"
SEMANTIC_JOB_TYPE_TRAIN = "train"
SEMANTIC_JOB_TYPE_PROMOTE = "promote"

SEMANTIC_JOB_STATUS_PENDING = "pending"
SEMANTIC_JOB_STATUS_RUNNING = "running"
SEMANTIC_JOB_STATUS_SUCCEEDED = "succeeded"
SEMANTIC_JOB_STATUS_FAILED = "failed"
SEMANTIC_JOB_STATUS_CANCELLED = "cancelled"

_VALID_JOB_TYPES = {SEMANTIC_JOB_TYPE_DATASET, SEMANTIC_JOB_TYPE_TRAIN, SEMANTIC_JOB_TYPE_PROMOTE}


class DatasetJobPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_slug: str
    augmentation_mode: str


class TrainJobPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str
    model_slug: str
    base_model_key: str
    base_model: str
    embedding_dim: int
    skip_fine_tune: bool
    epochs: int
    batch_size: int
    promote_after_register: bool
    embed_batch_size: int


class PromoteJobPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    embed_batch_size: int


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def list_semantic_jobs(db: Session) -> list[SemanticJob]:
    return db.scalars(select(SemanticJob).order_by(SemanticJob.created_at.desc(), SemanticJob.id.desc())).all()


def get_semantic_job(db: Session, job_id: str) -> SemanticJob | None:
    return db.get(SemanticJob, job_id)


def create_dataset_job(
    db: Session,
    *,
    requested_by: str,
    dataset_slug: str,
    augmentation_mode: str,
) -> SemanticJob:
    return _create_semantic_job(
        db,
        job_type=SEMANTIC_JOB_TYPE_DATASET,
        requested_by=requested_by,
        dataset_id=None,
        model_id=None,
        payload_json={
            "dataset_slug": dataset_slug,
            "augmentation_mode": augmentation_mode,
        },
    )


def create_train_job(
    db: Session,
    *,
    requested_by: str,
    dataset_id: str,
    model_slug: str,
    base_model_key: str,
    base_model: str,
    embedding_dim: int,
    skip_fine_tune: bool,
    epochs: int,
    batch_size: int,
    promote_after_register: bool,
    embed_batch_size: int,
) -> SemanticJob:
    if db.get(SemanticDataset, dataset_id) is None:
        raise KeyError(f"Semantic dataset {dataset_id} not found.")
    return _create_semantic_job(
        db,
        job_type=SEMANTIC_JOB_TYPE_TRAIN,
        requested_by=requested_by,
        dataset_id=dataset_id,
        model_id=None,
        payload_json={
            "dataset_id": dataset_id,
            "model_slug": model_slug,
            "base_model_key": base_model_key,
            "base_model": base_model,
            "embedding_dim": embedding_dim,
            "skip_fine_tune": skip_fine_tune,
            "epochs": epochs,
            "batch_size": batch_size,
            "promote_after_register": promote_after_register,
            "embed_batch_size": embed_batch_size,
        },
    )


def create_promote_job(
    db: Session,
    *,
    requested_by: str,
    model_id: str,
    embed_batch_size: int,
) -> SemanticJob:
    if db.get(SemanticModel, model_id) is None:
        raise KeyError(f"Semantic model {model_id} not found.")

    existing = db.scalar(
        select(SemanticJob.id)
        .where(SemanticJob.job_type == SEMANTIC_JOB_TYPE_PROMOTE)
        .where(SemanticJob.status.in_([SEMANTIC_JOB_STATUS_PENDING, SEMANTIC_JOB_STATUS_RUNNING]))
        .limit(1)
    )
    if existing is not None:
        raise RuntimeError("Another semantic promote job is already pending or running.")

    return _create_semantic_job(
        db,
        job_type=SEMANTIC_JOB_TYPE_PROMOTE,
        requested_by=requested_by,
        dataset_id=None,
        model_id=model_id,
        payload_json={
            "model_id": model_id,
            "embed_batch_size": embed_batch_size,
        },
    )


def claim_next_semantic_job(job_type: str, *, job_id: str | None = None) -> SemanticJob | None:
    if job_type not in _VALID_JOB_TYPES:
        raise ValueError(f"Unsupported semantic job type '{job_type}'.")

    with SessionLocal() as db:
        if job_id is not None:
            target = db.get(SemanticJob, job_id)
            if target is None:
                raise KeyError(f"Semantic job {job_id} not found.")
            if target.job_type != job_type:
                raise ValueError(f"Semantic job {job_id} is type '{target.job_type}', not '{job_type}'.")
            target_job_ids = [job_id]
        else:
            target_stmt = (
                select(SemanticJob.id)
                .where(SemanticJob.job_type == job_type)
                .where(SemanticJob.status == SEMANTIC_JOB_STATUS_PENDING)
                .order_by(SemanticJob.created_at.asc(), SemanticJob.id.asc())
            )
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                target_stmt = target_stmt.with_for_update(skip_locked=True)
            target_job_ids = db.scalars(target_stmt).all()
            if not target_job_ids:
                return None

        for target_job_id in target_job_ids:
            now = _utcnow_naive()
            result = db.execute(
                update(SemanticJob)
                .where(SemanticJob.id == target_job_id)
                .where(SemanticJob.status == SEMANTIC_JOB_STATUS_PENDING)
                .values(
                    status=SEMANTIC_JOB_STATUS_RUNNING,
                    started_at=now,
                    heartbeat_at=now,
                    finished_at=None,
                    error_message=None,
                )
            )
            if result.rowcount != 1:
                db.rollback()
                current = db.get(SemanticJob, target_job_id)
                if job_id is not None:
                    if current is None:
                        raise KeyError(f"Semantic job {target_job_id} not found.")
                    raise RuntimeError(
                        f"Semantic job {target_job_id} is not pending (current status: {current.status})."
                    )
                continue

            db.commit()
            claimed = db.get(SemanticJob, target_job_id)
            if claimed is None:
                raise KeyError(f"Semantic job {target_job_id} not found after claim.")
            return claimed

        return None


def touch_semantic_job_heartbeat(job_id: str) -> bool:
    with SessionLocal() as db:
        result = db.execute(
            update(SemanticJob)
            .where(SemanticJob.id == job_id)
            .where(SemanticJob.status == SEMANTIC_JOB_STATUS_RUNNING)
            .values(heartbeat_at=_utcnow_naive())
        )
        if result.rowcount != 1:
            db.rollback()
            return False
        db.commit()
        return True


def fail_stale_running_jobs(*, job_type: str, stale_after_seconds: float) -> list[str]:
    if job_type not in _VALID_JOB_TYPES:
        raise ValueError(f"Unsupported semantic job type '{job_type}'.")

    stale_before = _utcnow_naive() - timedelta(seconds=max(stale_after_seconds, 0.0))
    error_message = (
        f"Semantic {job_type} job heartbeat went stale after {int(max(stale_after_seconds, 0.0))} seconds."
    )

    with SessionLocal() as db:
        stale_jobs = db.execute(
            select(SemanticJob.id, SemanticJob.model_id, SemanticJob.dataset_id)
            .where(SemanticJob.job_type == job_type)
            .where(SemanticJob.status == SEMANTIC_JOB_STATUS_RUNNING)
            .where(func.coalesce(SemanticJob.heartbeat_at, SemanticJob.started_at, SemanticJob.created_at) < stale_before)
            .order_by(SemanticJob.created_at.asc(), SemanticJob.id.asc())
        ).all()
        stale_job_ids = [str(row.id) for row in stale_jobs]
        if not stale_job_ids:
            return []

        db.execute(
            update(SemanticJob)
            .where(SemanticJob.id.in_(stale_job_ids))
            .where(SemanticJob.status == SEMANTIC_JOB_STATUS_RUNNING)
            .values(
                status=SEMANTIC_JOB_STATUS_FAILED,
                finished_at=_utcnow_naive(),
                error_message=error_message,
            )
        )
        if job_type == SEMANTIC_JOB_TYPE_PROMOTE:
            _release_stale_promote_models(
                db,
                model_ids=[str(row.model_id) for row in stale_jobs if row.model_id is not None],
                error_message=error_message,
            )
        if job_type == SEMANTIC_JOB_TYPE_DATASET:
            _mark_stale_datasets_failed(
                db,
                dataset_ids=[str(row.dataset_id) for row in stale_jobs if row.dataset_id is not None],
                error_message=error_message,
            )
        db.commit()
        return stale_job_ids


def _release_stale_promote_models(db: Session, *, model_ids: list[str], error_message: str) -> None:
    if not model_ids:
        return

    target_model_ids = sorted(set(model_ids))
    db.execute(
        update(SemanticModel)
        .where(SemanticModel.id.in_(target_model_ids))
        .where(SemanticModel.status == "embedding")
        .values(status="failed", is_active=False, error_message=error_message[:4000])
    )
    db.query(SemanticModelEmbedding).filter(SemanticModelEmbedding.model_id.in_(target_model_ids)).delete(
        synchronize_session=False
    )


def _mark_stale_datasets_failed(db: Session, *, dataset_ids: list[str], error_message: str) -> None:
    if not dataset_ids:
        return
    db.execute(
        update(SemanticDataset)
        .where(SemanticDataset.id.in_(sorted(set(dataset_ids))))
        .where(SemanticDataset.status != "ready")
        .values(status="failed", error_message=error_message[:4000])
    )


def mark_semantic_job_succeeded(
    job_id: str,
    *,
    model_id: str | None = None,
    dataset_id: str | None = None,
    result_json: dict[str, object] | None = None,
) -> SemanticJob:
    with SessionLocal() as db:
        finished_at = _utcnow_naive()
        result = db.execute(
            update(SemanticJob)
            .where(SemanticJob.id == job_id)
            .where(SemanticJob.status == SEMANTIC_JOB_STATUS_RUNNING)
            .values(
                status=SEMANTIC_JOB_STATUS_SUCCEEDED,
                model_id=model_id,
                dataset_id=dataset_id,
                result_json=result_json,
                heartbeat_at=finished_at,
                finished_at=finished_at,
                error_message=None,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise RuntimeError(f"Semantic job {job_id} is not running.")
        db.commit()
        job = db.get(SemanticJob, job_id)
        if job is None:
            raise KeyError(f"Semantic job {job_id} not found after success.")
        return job


def mark_semantic_job_failed(
    job_id: str,
    *,
    error_message: str,
    model_id: str | None = None,
    dataset_id: str | None = None,
    result_json: dict[str, object] | None = None,
) -> SemanticJob:
    with SessionLocal() as db:
        finished_at = _utcnow_naive()
        result = db.execute(
            update(SemanticJob)
            .where(SemanticJob.id == job_id)
            .where(SemanticJob.status == SEMANTIC_JOB_STATUS_RUNNING)
            .values(
                status=SEMANTIC_JOB_STATUS_FAILED,
                model_id=model_id,
                dataset_id=dataset_id,
                result_json=result_json,
                error_message=error_message[:4000],
                heartbeat_at=finished_at,
                finished_at=finished_at,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            current = db.get(SemanticJob, job_id)
            if current is None:
                raise KeyError(f"Semantic job {job_id} not found.")
            raise RuntimeError(f"Semantic job {job_id} is not running.")
        db.commit()
        job = db.get(SemanticJob, job_id)
        if job is None:
            raise KeyError(f"Semantic job {job_id} not found after failure.")
        return job


def parse_dataset_job_payload(payload_json: dict[str, object] | None) -> DatasetJobPayload:
    return DatasetJobPayload.model_validate(payload_json or {})


def parse_train_job_payload(payload_json: dict[str, object] | None) -> TrainJobPayload:
    return TrainJobPayload.model_validate(payload_json or {})


def parse_promote_job_payload(payload_json: dict[str, object] | None) -> PromoteJobPayload:
    return PromoteJobPayload.model_validate(payload_json or {})


def _create_semantic_job(
    db: Session,
    *,
    job_type: str,
    requested_by: str,
    dataset_id: str | None,
    model_id: str | None,
    payload_json: dict[str, object],
) -> SemanticJob:
    normalized_requested_by = requested_by.strip()
    if not normalized_requested_by:
        raise ValueError("requested_by must not be empty.")
    if job_type not in _VALID_JOB_TYPES:
        raise ValueError(f"Unsupported semantic job type '{job_type}'.")

    job = SemanticJob(
        job_type=job_type,
        status=SEMANTIC_JOB_STATUS_PENDING,
        requested_by=normalized_requested_by,
        dataset_id=dataset_id,
        model_id=model_id,
        payload_json=payload_json,
        result_json=None,
        error_message=None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
