from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import admin_jwt_secret, admin_password
from ...core.database import get_db
from ...core.models import SemanticDataset, SemanticModel
from ...semantic.artifacts import (
    SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON,
    SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
    list_semantic_dataset_artifacts,
    list_semantic_model_artifacts,
)
from ...semantic.base_model_catalog import get_semantic_base_model, list_semantic_base_models
from ...semantic.dataset_registry import get_semantic_dataset, list_semantic_datasets
from ...semantic.model_registry import (
    count_semantic_model_embeddings,
    get_semantic_model,
    list_semantic_models,
)
from ...semantic.bundle_registration import register_model_bundle_bytes
from ...semantic.semantic_jobs import (
    SEMANTIC_JOB_STATUS_PENDING,
    create_dataset_job,
    create_promote_job,
    create_train_job,
    get_semantic_job,
    list_semantic_jobs,
)
from ...semantic.train_options import EMBED_BATCH_SIZE_OPTIONS, TRAIN_AUGMENTATION_OPTIONS, TRAIN_BATCH_SIZE_OPTIONS
from ..admin_auth import (
    admin_token_ttl_seconds,
    create_admin_token,
    ensure_admin_ip_not_locked_out,
    get_admin_client_ip,
    register_admin_login_failure,
    require_admin_token,
    reset_admin_login_failures,
)
from ..schemas import (
    AdminAuthTokenRequest,
    AdminAuthTokenResponse,
    SemanticBaseModelOption,
    SemanticDatasetArtifactSummary,
    SemanticDatasetDetail,
    SemanticDatasetJobCreate,
    SemanticDatasetSummary,
    SemanticJobDetail,
    SemanticJobSummary,
    SemanticModelArtifactSummary,
    SemanticModelDetail,
    SemanticModelPromoteRequest,
    SemanticModelPromotionAccepted,
    SemanticModelSummary,
    SemanticPromoteJobCreate,
    SemanticTrainAugmentationOption,
    SemanticTrainJobCreate,
    SemanticTrainOptions,
)

logger = logging.getLogger("ot_backend.api")

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _bundle_artifact_summary(model: SemanticModel) -> tuple[str, int] | None:
    for artifact in model.artifacts:
        if artifact.artifact_kind == SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP:
            return artifact.sha256, artifact.size_bytes
    return None


def _dataset_artifact_summary(dataset: SemanticDataset) -> tuple[str, int] | None:
    for artifact in dataset.artifacts:
        if artifact.artifact_kind == SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON:
            return artifact.sha256, artifact.size_bytes
    return None


def _serialize_semantic_model(model: SemanticModel, *, embedding_count: int | None = None) -> SemanticModelDetail:
    count = embedding_count if embedding_count is not None else 0
    bundle = _bundle_artifact_summary(model)
    base_model_key = None
    config_json = model.config_json or {}
    raw_base_model_key = config_json.get("base_model_key")
    if isinstance(raw_base_model_key, str):
        base_model_key = raw_base_model_key
    return SemanticModelDetail(
        id=model.id,
        slug=model.slug,
        base_model_key=base_model_key,
        base_model=model.base_model,
        status=model.status,
        is_active=model.is_active,
        embedding_dim=model.embedding_dim,
        artifact_sha256=bundle[0] if bundle else "",
        artifact_size_bytes=bundle[1] if bundle else 0,
        created_at=model.created_at,
        activated_at=model.activated_at,
        error_message=model.error_message,
        config_json=model.config_json,
        metrics_json=model.metrics_json,
        embedding_count=count,
    )


def _serialize_semantic_model_summary(model: SemanticModel) -> SemanticModelSummary:
    bundle = _bundle_artifact_summary(model)
    base_model_key = None
    config_json = model.config_json or {}
    raw_base_model_key = config_json.get("base_model_key")
    if isinstance(raw_base_model_key, str):
        base_model_key = raw_base_model_key
    return SemanticModelSummary(
        id=model.id,
        slug=model.slug,
        base_model_key=base_model_key,
        base_model=model.base_model,
        status=model.status,
        is_active=model.is_active,
        embedding_dim=model.embedding_dim,
        artifact_sha256=bundle[0] if bundle else "",
        artifact_size_bytes=bundle[1] if bundle else 0,
        created_at=model.created_at,
        activated_at=model.activated_at,
        error_message=model.error_message,
    )


def _serialize_semantic_dataset(dataset: SemanticDataset) -> SemanticDatasetDetail:
    return SemanticDatasetDetail(
        id=dataset.id,
        slug=dataset.slug,
        status=dataset.status,
        augmentation_mode=dataset.augmentation_mode,
        created_at=dataset.created_at,
        source_semantic_data_version=dataset.source_semantic_data_version,
        error_message=dataset.error_message,
        config_json=dataset.config_json,
        metrics_json=dataset.metrics_json,
    )


def _serialize_semantic_dataset_summary(dataset: SemanticDataset) -> SemanticDatasetSummary:
    return SemanticDatasetSummary(
        id=dataset.id,
        slug=dataset.slug,
        status=dataset.status,
        augmentation_mode=dataset.augmentation_mode,
        created_at=dataset.created_at,
        source_semantic_data_version=dataset.source_semantic_data_version,
        error_message=dataset.error_message,
    )


def parse_optional_json_header(raw_value: str | None, header_name: str) -> dict[str, object] | None:
    if raw_value is None or not raw_value.strip():
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{header_name} must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{header_name} must decode to a JSON object.")
    return parsed


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/auth/token", response_model=AdminAuthTokenResponse)
def admin_auth_token(payload: AdminAuthTokenRequest, request: Request) -> AdminAuthTokenResponse:
    configured_password = admin_password()
    if not configured_password or not admin_jwt_secret():
        raise HTTPException(status_code=503, detail="Admin auth is not configured.")
    client_ip = get_admin_client_ip(request)
    ensure_admin_ip_not_locked_out(client_ip)
    if payload.password != configured_password:
        register_admin_login_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid admin password.")
    reset_admin_login_failures(client_ip)
    return AdminAuthTokenResponse(
        access_token=create_admin_token(),
        expires_in=admin_token_ttl_seconds(),
    )


@router.get("/semantic-models", response_model=list[SemanticModelSummary])
def admin_list_semantic_models(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticModelSummary]:
    return [_serialize_semantic_model_summary(model) for model in list_semantic_models(db)]


@router.get("/semantic-datasets", response_model=list[SemanticDatasetSummary])
def admin_list_semantic_datasets(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticDatasetSummary]:
    return [_serialize_semantic_dataset_summary(dataset) for dataset in list_semantic_datasets(db)]


@router.get("/semantic-base-models", response_model=list[SemanticBaseModelOption])
def admin_list_semantic_base_models(_: None = Depends(require_admin_token)) -> list[SemanticBaseModelOption]:
    return [
        SemanticBaseModelOption(
            key=spec.key,
            label=spec.label,
            base_model=spec.base_model,
            embedding_dim=spec.embedding_dim,
        )
        for spec in list_semantic_base_models()
    ]


@router.get("/semantic-train-options", response_model=SemanticTrainOptions)
def admin_get_semantic_train_options(_: None = Depends(require_admin_token)) -> SemanticTrainOptions:
    return SemanticTrainOptions(
        batch_size_options=list(TRAIN_BATCH_SIZE_OPTIONS),
        embed_batch_size_options=list(EMBED_BATCH_SIZE_OPTIONS),
        augmentation_options=[
            SemanticTrainAugmentationOption(
                key=option.key,
                label=option.label,
                description=option.description,
                default_enabled=option.default_enabled,
            )
            for option in TRAIN_AUGMENTATION_OPTIONS
        ],
    )


@router.get("/semantic-models/{model_id}", response_model=SemanticModelDetail)
def admin_get_semantic_model(
    model_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticModelDetail:
    model = get_semantic_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Semantic model not found.")
    return _serialize_semantic_model(model, embedding_count=count_semantic_model_embeddings(db, model_id))


@router.get("/semantic-models/{model_id}/artifacts", response_model=list[SemanticModelArtifactSummary])
def admin_list_semantic_model_artifacts(
    model_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticModelArtifactSummary]:
    model = get_semantic_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Semantic model not found.")
    return [SemanticModelArtifactSummary.model_validate(artifact) for artifact in list_semantic_model_artifacts(db, model_id)]


@router.get("/semantic-datasets/{dataset_id}", response_model=SemanticDatasetDetail)
def admin_get_semantic_dataset(
    dataset_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticDatasetDetail:
    dataset = get_semantic_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Semantic dataset not found.")
    return _serialize_semantic_dataset(dataset)


@router.get("/semantic-datasets/{dataset_id}/artifacts", response_model=list[SemanticDatasetArtifactSummary])
def admin_list_semantic_dataset_artifacts(
    dataset_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticDatasetArtifactSummary]:
    dataset = get_semantic_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Semantic dataset not found.")
    return [SemanticDatasetArtifactSummary.model_validate(artifact) for artifact in list_semantic_dataset_artifacts(db, dataset_id)]


@router.post("/semantic-models", response_model=SemanticModelDetail, status_code=status.HTTP_201_CREATED)
async def admin_register_semantic_model(
    request: Request,
    _: None = Depends(require_admin_token),
    slug: str = Query(..., min_length=1, max_length=120),
    base_model_key: str = Query(..., min_length=1, max_length=120),
    db: Session = Depends(get_db),
) -> SemanticModelDetail:
    bundle_bytes = await request.body()
    if not bundle_bytes:
        raise HTTPException(status_code=400, detail="Semantic model bundle body is required.")

    try:
        base_model_spec = get_semantic_base_model(base_model_key)
        config_json = parse_optional_json_header(request.headers.get("x-semantic-config-json"), "X-Semantic-Config-Json")
        metrics_json = parse_optional_json_header(
            request.headers.get("x-semantic-metrics-json"),
            "X-Semantic-Metrics-Json",
        )
        merged_config = dict(config_json or {})
        merged_config["base_model_key"] = base_model_spec.key
        model = register_model_bundle_bytes(
            db,
            slug=slug,
            base_model=base_model_spec.base_model,
            embedding_dim=base_model_spec.embedding_dim,
            artifact_bundle_bytes=bundle_bytes,
            dataset_bytes=None,
            source_semantic_data_version=None,
            augmentation_mode="none",
            config_json=merged_config,
            metrics_json=metrics_json,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Semantic model slug '{slug}' already exists.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    loaded_model = get_semantic_model(db, model.id)
    if loaded_model is None:
        raise HTTPException(status_code=500, detail="Model disappeared after registration.")
    return _serialize_semantic_model(loaded_model)


@router.get("/semantic-jobs", response_model=list[SemanticJobSummary])
def admin_list_semantic_jobs(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticJobSummary]:
    return [SemanticJobSummary.model_validate(job) for job in list_semantic_jobs(db)]


@router.get("/semantic-jobs/{job_id}", response_model=SemanticJobDetail)
def admin_get_semantic_job(
    job_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticJobDetail:
    job = get_semantic_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Semantic job not found.")
    return SemanticJobDetail.model_validate(job)


@router.post("/semantic-jobs/train", response_model=SemanticJobDetail, status_code=status.HTTP_201_CREATED)
def admin_create_train_job(
    payload: SemanticTrainJobCreate,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticJobDetail:
    try:
        base_model_spec = get_semantic_base_model(payload.base_model_key)
        job = create_train_job(
            db,
            requested_by=payload.requested_by,
            dataset_id=payload.dataset_id,
            model_slug=payload.model_slug,
            base_model_key=payload.base_model_key,
            base_model=base_model_spec.base_model,
            embedding_dim=base_model_spec.embedding_dim,
            skip_fine_tune=payload.skip_fine_tune,
            epochs=payload.epochs,
            batch_size=payload.batch_size,
            promote_after_register=payload.promote_after_register,
            embed_batch_size=payload.embed_batch_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SemanticJobDetail.model_validate(job)


@router.post("/semantic-jobs/dataset", response_model=SemanticJobDetail, status_code=status.HTTP_201_CREATED)
def admin_create_dataset_job(
    payload: SemanticDatasetJobCreate,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticJobDetail:
    try:
        job = create_dataset_job(
            db,
            requested_by=payload.requested_by,
            dataset_slug=payload.dataset_slug,
            augmentation_mode=payload.augmentation_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SemanticJobDetail.model_validate(job)


@router.post("/semantic-jobs/promote", response_model=SemanticJobDetail, status_code=status.HTTP_201_CREATED)
def admin_create_promote_job(
    payload: SemanticPromoteJobCreate,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticJobDetail:
    try:
        job = create_promote_job(
            db,
            requested_by=payload.requested_by,
            model_id=payload.model_id,
            embed_batch_size=payload.embed_batch_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SemanticJobDetail.model_validate(job)


@router.post(
    "/semantic-models/{model_id}/promote",
    response_model=SemanticModelPromotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def admin_promote_semantic_model(
    model_id: str,
    payload: SemanticModelPromoteRequest,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticModelPromotionAccepted:
    try:
        job = create_promote_job(
            db,
            requested_by=payload.requested_by,
            model_id=model_id,
            embed_batch_size=payload.embed_batch_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SemanticModelPromotionAccepted(
        accepted=True,
        job_id=job.id,
        model_id=model_id,
        status=SEMANTIC_JOB_STATUS_PENDING,
    )
