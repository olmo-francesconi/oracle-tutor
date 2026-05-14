from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...core.config import admin_jwt_secret, admin_password
from ...core.database import get_db
from ...core.models import SemanticDataset, SemanticModel
from ...semantic.artifacts import (
    SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
    list_semantic_dataset_artifacts,
    list_semantic_model_artifacts,
)
from ...semantic.dataset_registry import get_semantic_dataset, list_semantic_datasets
from ...semantic.model_registry import (
    count_semantic_model_embeddings,
    get_semantic_model,
    list_semantic_models,
)
from ..admin_auth import (
    admin_token_ttl_seconds,
    create_admin_token,
    ensure_admin_ip_not_locked_out,
    get_admin_client_ip,
    register_admin_login_failure,
    require_admin_token,
    require_cloudflare_access,
    reset_admin_login_failures,
)
from ..schemas import (
    AdminAuthTokenRequest,
    AdminAuthTokenResponse,
    SemanticDatasetArtifactSummary,
    SemanticDatasetDetail,
    SemanticDatasetSummary,
    SemanticModelArtifactSummary,
    SemanticModelDetail,
    SemanticModelSummary,
)

logger = logging.getLogger("ot_backend.api")

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_cloudflare_access)],
)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _bundle_artifact_summary(model: SemanticModel) -> tuple[str | None, int] | None:
    for artifact in model.artifacts:
        if artifact.artifact_kind == SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP:
            return artifact.sha256, artifact.size_bytes
    return None


def _semantic_model_shared_fields(model: SemanticModel) -> dict[str, Any]:
    bundle = _bundle_artifact_summary(model)
    base_model_key = None
    raw_base_model_key = (model.config_json or {}).get("base_model_key")
    if isinstance(raw_base_model_key, str):
        base_model_key = raw_base_model_key
    return {
        "id": model.id,
        "slug": model.slug,
        "base_model_key": base_model_key,
        "base_model": model.base_model,
        "status": model.status,
        "is_active": model.is_active,
        "embedding_dim": model.embedding_dim,
        "artifact_sha256": (bundle[0] if bundle else None) or "",
        "artifact_size_bytes": bundle[1] if bundle else 0,
        "created_at": model.created_at,
        "activated_at": model.activated_at,
        "error_message": model.error_message,
    }


def _serialize_semantic_model(model: SemanticModel, *, embedding_count: int | None = None) -> SemanticModelDetail:
    return SemanticModelDetail(
        **_semantic_model_shared_fields(model),
        config_json=model.config_json,
        metrics_json=model.metrics_json,
        embedding_count=embedding_count if embedding_count is not None else 0,
    )


def _serialize_semantic_model_summary(model: SemanticModel) -> SemanticModelSummary:
    return SemanticModelSummary(**_semantic_model_shared_fields(model))


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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/auth/token", response_model=AdminAuthTokenResponse)
def admin_auth_token(
    payload: AdminAuthTokenRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> AdminAuthTokenResponse:
    configured_password = admin_password()
    if not configured_password or not admin_jwt_secret():
        raise HTTPException(status_code=503, detail="Admin auth is not configured.")
    client_ip = get_admin_client_ip(request)
    ensure_admin_ip_not_locked_out(db, client_ip)
    if not hmac.compare_digest(payload.password.encode("utf-8"), configured_password.encode("utf-8")):
        register_admin_login_failure(db, client_ip)
        raise HTTPException(status_code=401, detail="Invalid admin password.")
    reset_admin_login_failures(db, client_ip)
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
