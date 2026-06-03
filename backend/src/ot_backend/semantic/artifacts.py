from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import artifact_bucket_client, artifact_bucket_name
from ..core.models import SemanticDatasetArtifact, SemanticModelArtifact

SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP = "bundle_zip"
SEMANTIC_MODEL_ARTIFACT_KIND_TRAINING_DATASET = "training_dataset"
SEMANTIC_MODEL_ARTIFACT_KIND_EVAL_JSON = "eval_json"
SEMANTIC_MODEL_ARTIFACT_KIND_MANIFEST_JSON = "manifest_json"

SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON = "dataset_json"
SEMANTIC_DATASET_ARTIFACT_KIND_MANIFEST_JSON = "manifest_json"

_ARTIFACT_KEY_PREFIX = "semantic-registry"
_MODEL_ARTIFACT_FILENAMES = {
    SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP: "bundle.zip",
    SEMANTIC_MODEL_ARTIFACT_KIND_TRAINING_DATASET: "training-dataset.json",
    SEMANTIC_MODEL_ARTIFACT_KIND_EVAL_JSON: "eval.json",
    SEMANTIC_MODEL_ARTIFACT_KIND_MANIFEST_JSON: "manifest.json",
}
_DATASET_ARTIFACT_FILENAMES = {
    SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON: "training-dataset.json",
    SEMANTIC_DATASET_ARTIFACT_KIND_MANIFEST_JSON: "manifest.json",
}


def semantic_model_artifact_object_key(model_id: str, artifact_kind: str) -> str:
    filename = _MODEL_ARTIFACT_FILENAMES.get(artifact_kind)
    if filename is None:
        raise ValueError(f"Unsupported semantic model artifact kind: {artifact_kind}")
    return f"{_ARTIFACT_KEY_PREFIX}/models/{model_id}/{filename}"


def semantic_dataset_artifact_object_key(dataset_id: str, artifact_kind: str) -> str:
    filename = _DATASET_ARTIFACT_FILENAMES.get(artifact_kind)
    if filename is None:
        raise ValueError(f"Unsupported semantic dataset artifact kind: {artifact_kind}")
    return f"{_ARTIFACT_KEY_PREFIX}/datasets/{dataset_id}/{filename}"


def upload_artifact_bytes(*, object_key: str, content_bytes: bytes, content_type: str) -> None:
    client = artifact_bucket_client()
    client.put_object(
        Bucket=artifact_bucket_name(),
        Key=object_key,
        Body=content_bytes,
        ContentType=content_type,
    )


def download_artifact_bytes(*, object_key: str) -> bytes:
    client = artifact_bucket_client()
    response = client.get_object(Bucket=artifact_bucket_name(), Key=object_key)
    return response["Body"].read()


def delete_artifact_object(*, object_key: str) -> None:
    client = artifact_bucket_client()
    client.delete_object(Bucket=artifact_bucket_name(), Key=object_key)


def _record_artifact(
    artifact: SemanticModelArtifact | SemanticDatasetArtifact,
    *,
    object_key: str,
    content_bytes: bytes,
    content_type: str,
    metadata_json: dict[str, object] | None,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    artifact.object_key = object_key
    artifact.sha256 = hashlib.sha256(content_bytes).hexdigest()
    artifact.size_bytes = len(content_bytes)
    artifact.content_type = content_type
    artifact.metadata_json = metadata_json
    artifact.created_at = getattr(artifact, "created_at", None) or now


def record_semantic_model_artifact(
    db: Session,
    *,
    model_id: str,
    artifact_kind: str,
    object_key: str,
    content_bytes: bytes,
    content_type: str,
    metadata_json: dict[str, object] | None = None,
) -> SemanticModelArtifact:
    artifact = db.execute(
        select(SemanticModelArtifact)
        .where(SemanticModelArtifact.model_id == model_id)
        .where(SemanticModelArtifact.artifact_kind == artifact_kind)
    ).scalar_one_or_none()
    if artifact is None:
        artifact = SemanticModelArtifact(model_id=model_id, artifact_kind=artifact_kind)
        db.add(artifact)
    _record_artifact(
        artifact,
        object_key=object_key,
        content_bytes=content_bytes,
        content_type=content_type,
        metadata_json=metadata_json,
    )
    db.flush()
    return artifact


def record_semantic_dataset_artifact(
    db: Session,
    *,
    dataset_id: str,
    artifact_kind: str,
    object_key: str,
    content_bytes: bytes,
    content_type: str,
    metadata_json: dict[str, object] | None = None,
) -> SemanticDatasetArtifact:
    artifact = db.execute(
        select(SemanticDatasetArtifact)
        .where(SemanticDatasetArtifact.dataset_id == dataset_id)
        .where(SemanticDatasetArtifact.artifact_kind == artifact_kind)
    ).scalar_one_or_none()
    if artifact is None:
        artifact = SemanticDatasetArtifact(dataset_id=dataset_id, artifact_kind=artifact_kind)
        db.add(artifact)
    _record_artifact(
        artifact,
        object_key=object_key,
        content_bytes=content_bytes,
        content_type=content_type,
        metadata_json=metadata_json,
    )
    db.flush()
    return artifact


def upload_and_record_semantic_model_artifact(
    db: Session,
    *,
    model_id: str,
    artifact_kind: str,
    content_bytes: bytes,
    content_type: str,
    metadata_json: dict[str, object] | None = None,
) -> SemanticModelArtifact:
    object_key = semantic_model_artifact_object_key(model_id, artifact_kind)
    upload_artifact_bytes(object_key=object_key, content_bytes=content_bytes, content_type=content_type)
    return record_semantic_model_artifact(
        db,
        model_id=model_id,
        artifact_kind=artifact_kind,
        object_key=object_key,
        content_bytes=content_bytes,
        content_type=content_type,
        metadata_json=metadata_json,
    )


def upload_and_record_semantic_dataset_artifact(
    db: Session,
    *,
    dataset_id: str,
    artifact_kind: str,
    content_bytes: bytes,
    content_type: str,
    metadata_json: dict[str, object] | None = None,
) -> SemanticDatasetArtifact:
    object_key = semantic_dataset_artifact_object_key(dataset_id, artifact_kind)
    upload_artifact_bytes(object_key=object_key, content_bytes=content_bytes, content_type=content_type)
    return record_semantic_dataset_artifact(
        db,
        dataset_id=dataset_id,
        artifact_kind=artifact_kind,
        object_key=object_key,
        content_bytes=content_bytes,
        content_type=content_type,
        metadata_json=metadata_json,
    )


def list_semantic_model_artifacts(db: Session, model_id: str) -> list[SemanticModelArtifact]:
    return list(
        db.scalars(
            select(SemanticModelArtifact)
            .where(SemanticModelArtifact.model_id == model_id)
            .order_by(SemanticModelArtifact.created_at.asc(), SemanticModelArtifact.id.asc())
        ).all()
    )


def list_semantic_dataset_artifacts(db: Session, dataset_id: str) -> list[SemanticDatasetArtifact]:
    return list(
        db.scalars(
            select(SemanticDatasetArtifact)
            .where(SemanticDatasetArtifact.dataset_id == dataset_id)
            .order_by(SemanticDatasetArtifact.created_at.asc(), SemanticDatasetArtifact.id.asc())
        ).all()
    )


def get_semantic_model_artifact(
    db: Session,
    *,
    model_id: str,
    artifact_kind: str,
) -> SemanticModelArtifact | None:
    return db.execute(
        select(SemanticModelArtifact)
        .where(SemanticModelArtifact.model_id == model_id)
        .where(SemanticModelArtifact.artifact_kind == artifact_kind)
    ).scalar_one_or_none()


def get_semantic_dataset_artifact(
    db: Session,
    *,
    dataset_id: str,
    artifact_kind: str,
) -> SemanticDatasetArtifact | None:
    return db.execute(
        select(SemanticDatasetArtifact)
        .where(SemanticDatasetArtifact.dataset_id == dataset_id)
        .where(SemanticDatasetArtifact.artifact_kind == artifact_kind)
    ).scalar_one_or_none()


# Manifest version 2 carries every field needed to rehydrate a SemanticModel /
# SemanticDataset row from S3 alone. Sync downloads only manifest.json — no
# bundle.zip / training-dataset.json round-trips. Backfill upgrades older
# manifests (or missing ones) in place.
SEMANTIC_MANIFEST_VERSION = 2


def build_semantic_model_manifest(
    *,
    bundle_bytes: bytes,
    base_model: str,
    embedding_dim: int,
    bundle_config: dict[str, object] | None,
    bundle_metrics: dict[str, object] | None,
    dataset_metadata: dict[str, object] | None,
    source_semantic_data_version: int | None,
) -> bytes:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        names = sorted(name for name in archive.namelist() if not name.endswith("/"))

    payload = {
        "version": SEMANTIC_MANIFEST_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "base_model": base_model,
        "embedding_dim": embedding_dim,
        "config": bundle_config or {},
        "metrics": bundle_metrics or {},
        "bundle": {
            "format": "zip",
            "entry_count": len(names),
            "has_onnx_model": any(name.endswith("onnx/model.onnx") or name.endswith("/model.onnx") or name == "model.onnx" for name in names),
            "has_pytorch_model": any(name.startswith("models/pytorch/") or name.startswith("pytorch/") for name in names),
            "has_precomputed_embeddings": any(name.endswith("embeddings/embeddings.npz") for name in names),
            "has_training_dataset": any(name.endswith("training/training-dataset.json") for name in names),
            "has_eval_json": any(name.endswith("eval/eval.json") for name in names),
        },
        "source_semantic_data_version": source_semantic_data_version,
        "dataset_metadata": dataset_metadata or {},
    }
    return json.dumps(payload, indent=2).encode("utf-8")


def build_semantic_dataset_manifest(
    *,
    dataset_metadata: dict[str, object] | None,
    augmentation_mode: str,
    source_semantic_data_version: int | None,
    dataset_metrics: dict[str, object] | None,
) -> bytes:
    payload = {
        "version": SEMANTIC_MANIFEST_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "augmentation_mode": augmentation_mode,
        "source_semantic_data_version": source_semantic_data_version,
        "dataset_metadata": dataset_metadata or {},
        "dataset_metrics": dataset_metrics or {},
    }
    return json.dumps(payload, indent=2).encode("utf-8")
