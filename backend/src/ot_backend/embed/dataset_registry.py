from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..core.models import SemanticDataset
from .artifacts import (
    SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON,
    SEMANTIC_DATASET_ARTIFACT_KIND_MANIFEST_JSON,
    build_semantic_dataset_manifest,
    get_semantic_dataset_artifact,
    upload_and_record_semantic_dataset_artifact,
)
from .registration import load_training_dataset_metadata_from_bytes
from .semantic_state import get_semantic_data_version

SEMANTIC_DATASET_STATUS_READY = "ready"
SEMANTIC_DATASET_STATUS_FAILED = "failed"


def create_semantic_dataset(
    db: Session,
    *,
    slug: str,
    augmentation_mode: str,
    dataset_bytes: bytes,
    source_semantic_data_version: int | None = None,
    config_json: dict[str, object] | None = None,
    metrics_json: dict[str, object] | None = None,
) -> SemanticDataset:
    dataset_metadata = load_training_dataset_metadata_from_bytes(dataset_bytes)
    resolved_source_version = source_semantic_data_version
    if resolved_source_version is None:
        inferred = dataset_metadata.get("semantic_data_version")
        if isinstance(inferred, int):
            resolved_source_version = inferred
        elif isinstance(inferred, str) and inferred.isdigit():
            resolved_source_version = int(inferred)
        else:
            resolved_source_version = get_semantic_data_version(db)

    dataset = SemanticDataset(
        slug=slug,
        status=SEMANTIC_DATASET_STATUS_READY,
        augmentation_mode=augmentation_mode,
        source_semantic_data_version=resolved_source_version,
        config_json=config_json,
        metrics_json=metrics_json,
    )
    db.add(dataset)
    db.flush()

    upload_and_record_semantic_dataset_artifact(
        db,
        dataset_id=dataset.id,
        artifact_kind=SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON,
        content_bytes=dataset_bytes,
        content_type="application/json",
        metadata_json=dataset_metadata or None,
    )
    manifest_bytes = build_semantic_dataset_manifest(
        dataset_metadata=dataset_metadata,
        augmentation_mode=augmentation_mode,
        source_semantic_data_version=resolved_source_version,
    )
    upload_and_record_semantic_dataset_artifact(
        db,
        dataset_id=dataset.id,
        artifact_kind=SEMANTIC_DATASET_ARTIFACT_KIND_MANIFEST_JSON,
        content_bytes=manifest_bytes,
        content_type="application/json",
        metadata_json={
            "source_semantic_data_version": resolved_source_version,
            "augmentation_mode": augmentation_mode,
        },
    )
    db.commit()
    db.refresh(dataset)
    return dataset


def list_semantic_datasets(db: Session) -> list[SemanticDataset]:
    return db.scalars(
        select(SemanticDataset)
        .options(selectinload(SemanticDataset.artifacts))
        .order_by(SemanticDataset.created_at.desc(), SemanticDataset.id.desc())
    ).all()


def get_semantic_dataset(db: Session, dataset_id: str) -> SemanticDataset | None:
    return db.scalar(
        select(SemanticDataset)
        .options(selectinload(SemanticDataset.artifacts))
        .where(SemanticDataset.id == dataset_id)
    )


def get_semantic_dataset_by_slug(db: Session, slug: str) -> SemanticDataset | None:
    return db.scalar(
        select(SemanticDataset)
        .options(selectinload(SemanticDataset.artifacts))
        .where(SemanticDataset.slug == slug)
    )


def get_semantic_dataset_bytes(db: Session, dataset_id: str) -> bytes:
    artifact = get_semantic_dataset_artifact(
        db,
        dataset_id=dataset_id,
        artifact_kind=SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON,
    )
    if artifact is None:
        raise KeyError(f"Semantic dataset {dataset_id} does not have a dataset artifact.")
    from .artifacts import download_artifact_bytes

    return download_artifact_bytes(object_key=artifact.object_key)


def semantic_dataset_artifact_keys(db: Session, dataset_id: str) -> dict[str, str]:
    dataset = get_semantic_dataset(db, dataset_id)
    if dataset is None:
        raise KeyError(f"Semantic dataset {dataset_id} not found.")
    return {artifact.artifact_kind: artifact.object_key for artifact in dataset.artifacts}


def semantic_dataset_summary_metrics(dataset_bytes: bytes) -> dict[str, object]:
    payload = json.loads(dataset_bytes.decode("utf-8"))
    return {
        "face_count": len(payload.get("face_texts", [])),
        "pair_count": len(payload.get("pair_ids", [])),
        "direct_text_pair_count": len(payload.get("direct_text_pairs", [])),
        "template_query_examples": int(payload.get("template_query_examples", 0)),
        "llm_query_examples": int(payload.get("llm_query_examples", 0)),
    }
