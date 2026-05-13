from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from ..core.models import SemanticModel
from .artifacts import (
    SEMANTIC_MODEL_ARTIFACT_KIND_EVAL_JSON,
    SEMANTIC_MODEL_ARTIFACT_KIND_MANIFEST_JSON,
    SEMANTIC_MODEL_ARTIFACT_KIND_TRAINING_DATASET,
    build_semantic_model_manifest,
    list_semantic_model_artifacts,
    upload_and_record_semantic_model_artifact,
)
from .eval_service import summarize_eval_payload
from .model_registry import create_semantic_model, validate_model_bundle
from .semantic_state import get_semantic_data_version

_BUNDLE_CONFIG_PATH = "config.json"
_BUNDLE_METRICS_PATH = "metrics.json"
_BUNDLE_TRAINING_DATASET_PATH = "training/training-dataset.json"
_BUNDLE_EVAL_PATH = "eval/eval.json"


def _read_bundle_entry(bundle_bytes: bytes, entry_name: str) -> bytes | None:
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        try:
            return archive.read(entry_name)
        except KeyError:
            return None


def load_bundle_sidecar_json(bundle_bytes: bytes, filename: str) -> dict[str, object] | None:
    raw = _read_bundle_entry(bundle_bytes, filename)
    if raw is None:
        return None
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def load_training_dataset_metadata_from_bytes(dataset_bytes: bytes) -> dict[str, object]:
    payload = json.loads(dataset_bytes.decode("utf-8"))
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        return {}
    return {str(key): value for key, value in metadata.items()}


def _resolve_source_semantic_data_version(
    db: Session,
    *,
    source_semantic_data_version: int | None,
    dataset_metadata: dict[str, object],
) -> int:
    if source_semantic_data_version is not None:
        return source_semantic_data_version
    inferred = dataset_metadata.get("semantic_data_version")
    if isinstance(inferred, int):
        return inferred
    if isinstance(inferred, str) and inferred.isdigit():
        return int(inferred)
    return get_semantic_data_version(db)


def _read_npz_embedding_dim(raw_bytes: bytes) -> int:
    with np.load(io.BytesIO(raw_bytes), allow_pickle=False) as archive:
        embeddings = np.asarray(archive["embeddings"], dtype=np.float32)
    if embeddings.ndim != 2:
        raise ValueError("Semantic model bundle embeddings must be a 2D array.")
    return int(embeddings.shape[1])


def load_bundle_embedding_dim(bundle_bytes: bytes) -> int | None:
    embeddings_bytes = _read_bundle_entry(bundle_bytes, "embeddings/embeddings.npz")
    if embeddings_bytes is None:
        return None
    return _read_npz_embedding_dim(embeddings_bytes)


def _extract_candidate_dimensions(bundle_payload: dict[str, object]) -> list[int]:
    candidates: list[int] = []
    for key in ("embedding_dim", "dimension", "dim"):
        value = bundle_payload.get(key)
        if isinstance(value, int):
            candidates.append(value)
        elif isinstance(value, str) and value.isdigit():
            candidates.append(int(value))

    dataset_metadata = bundle_payload.get("dataset_metadata")
    if isinstance(dataset_metadata, dict):
        for key in ("embedding_dim", "dimension", "dim"):
            value = dataset_metadata.get(key)
            if isinstance(value, int):
                candidates.append(value)
            elif isinstance(value, str) and value.isdigit():
                candidates.append(int(value))
    return candidates


def validate_registered_bundle_dimensions(
    *,
    bundle_bytes: bytes,
    expected_embedding_dim: int,
) -> None:
    bundle_embedding_dim = load_bundle_embedding_dim(bundle_bytes)
    if bundle_embedding_dim is not None and bundle_embedding_dim != expected_embedding_dim:
        raise ValueError(
            "Semantic model bundle embedding dimension "
            f"{bundle_embedding_dim} does not match expected dimension {expected_embedding_dim}."
        )

    for path_name in ("config.json", "manifest.json", "metrics.json"):
        raw_bytes = _read_bundle_entry(bundle_bytes, path_name)
        if raw_bytes is None:
            continue
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        candidate_dimensions = _extract_candidate_dimensions(payload)
        for candidate_dimension in candidate_dimensions:
            if candidate_dimension != expected_embedding_dim:
                raise ValueError(
                    f"Semantic model bundle {Path(path_name).name} embedding dimension "
                    f"{candidate_dimension} does not match expected dimension {expected_embedding_dim}."
                )


def register_model_bundle_bytes(
    db: Session,
    *,
    slug: str,
    base_model: str,
    artifact_bundle_bytes: bytes,
    embedding_dim: int = 384,
    dataset_id: str | None = None,
    dataset_bytes: bytes | None = None,
    eval_bytes: bytes | None = None,
    source_semantic_data_version: int | None = None,
    augmentation_mode: str,
    config_json: dict[str, object] | None = None,
    metrics_json: dict[str, object] | None = None,
) -> SemanticModel:
    validate_model_bundle(artifact_bundle_bytes)
    validate_registered_bundle_dimensions(
        bundle_bytes=artifact_bundle_bytes,
        expected_embedding_dim=embedding_dim,
    )

    bundle_config = load_bundle_sidecar_json(artifact_bundle_bytes, _BUNDLE_CONFIG_PATH) or {}
    bundle_metrics = load_bundle_sidecar_json(artifact_bundle_bytes, _BUNDLE_METRICS_PATH) or {}
    resolved_dataset_bytes = dataset_bytes or _read_bundle_entry(artifact_bundle_bytes, _BUNDLE_TRAINING_DATASET_PATH)
    resolved_eval_bytes = eval_bytes or _read_bundle_entry(artifact_bundle_bytes, _BUNDLE_EVAL_PATH)
    dataset_metadata = (
        load_training_dataset_metadata_from_bytes(resolved_dataset_bytes)
        if resolved_dataset_bytes is not None
        else {}
    )
    resolved_source_version = _resolve_source_semantic_data_version(
        db,
        source_semantic_data_version=source_semantic_data_version,
        dataset_metadata=dataset_metadata,
    )

    merged_config = bundle_config | (config_json or {})
    merged_metrics = bundle_metrics | (metrics_json or {})
    merged_config["augmentation_mode"] = augmentation_mode
    if dataset_metadata:
        merged_config["dataset_metadata"] = dataset_metadata
    merged_config["semantic_data_version"] = resolved_source_version

    model = create_semantic_model(
        db,
        slug=slug,
        base_model=base_model,
        artifact_bundle_bytes=artifact_bundle_bytes,
        embedding_dim=embedding_dim,
        dataset_id=dataset_id,
        config_json=merged_config or None,
        metrics_json=merged_metrics or None,
    )

    if resolved_dataset_bytes is not None:
        upload_and_record_semantic_model_artifact(
            db,
            model_id=model.id,
            artifact_kind=SEMANTIC_MODEL_ARTIFACT_KIND_TRAINING_DATASET,
            content_bytes=resolved_dataset_bytes,
            content_type="application/json",
            metadata_json=dataset_metadata or None,
        )

    if resolved_eval_bytes is not None:
        eval_metadata = summarize_eval_payload(json.loads(resolved_eval_bytes.decode("utf-8")))
        upload_and_record_semantic_model_artifact(
            db,
            model_id=model.id,
            artifact_kind=SEMANTIC_MODEL_ARTIFACT_KIND_EVAL_JSON,
            content_bytes=resolved_eval_bytes,
            content_type="application/json",
            metadata_json=eval_metadata or None,
        )

    manifest_bytes = build_semantic_model_manifest(
        bundle_bytes=artifact_bundle_bytes,
        base_model=base_model,
        embedding_dim=embedding_dim,
        bundle_config=merged_config or None,
        bundle_metrics=merged_metrics or None,
        dataset_metadata=dataset_metadata,
        source_semantic_data_version=resolved_source_version,
    )
    upload_and_record_semantic_model_artifact(
        db,
        model_id=model.id,
        artifact_kind=SEMANTIC_MODEL_ARTIFACT_KIND_MANIFEST_JSON,
        content_bytes=manifest_bytes,
        content_type="application/json",
        metadata_json={
            "source_semantic_data_version": resolved_source_version,
            "has_training_dataset": resolved_dataset_bytes is not None,
            "has_eval_json": resolved_eval_bytes is not None,
        },
    )

    refreshed = db.get(SemanticModel, model.id)
    if refreshed is None:
        raise KeyError(f"Semantic model {model.id} disappeared during artifact registration.")
    db.commit()
    db.refresh(refreshed)
    return refreshed


def semantic_model_artifact_keys(db: Session, model_id: str) -> dict[str, str]:
    return {
        artifact.artifact_kind: artifact.object_key
        for artifact in list_semantic_model_artifacts(db, model_id)
    }
