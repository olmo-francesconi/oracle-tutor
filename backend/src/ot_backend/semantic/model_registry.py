from __future__ import annotations

import io
import logging
import shutil
import zipfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..core.config import semantic_temp_dir
from ..core.database import SessionLocal
from ..core.models import SemanticModel, SemanticModelEmbedding
from .artifacts import (
    SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
    SemanticModelArtifact,
    download_artifact_bytes,
    get_semantic_model_artifact,
    upload_and_record_semantic_model_artifact,
)

logger = logging.getLogger("ot_backend.semantic.model_registry")

SEMANTIC_MODEL_STATUS_UPLOADED = "uploaded"
SEMANTIC_MODEL_STATUS_EMBEDDING = "embedding"
SEMANTIC_MODEL_STATUS_READY = "ready"
SEMANTIC_MODEL_STATUS_ACTIVE = "active"
SEMANTIC_MODEL_STATUS_FAILED = "failed"
SEMANTIC_MODEL_STATUS_ARCHIVED = "archived"
_MODEL_ROOT_MARKER = ".model_root"
_REQUIRED_BUNDLE_FILES = (
    "config.json",
    "metrics.json",
    "manifest.json",
    "embeddings/embeddings.npz",
    "training/training-dataset.json",
    "eval/eval.json",
)


def bundle_model_directory(model_root: Path) -> bytes:
    if not model_root.exists() or not model_root.is_dir():
        raise FileNotFoundError(f"Semantic model directory not found: {model_root}")

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(model_root.rglob("*")):
            if path.is_dir():
                continue
            archive.write(path, arcname=path.relative_to(model_root).as_posix())
    bundle_bytes = output.getvalue()
    validate_model_bundle(bundle_bytes)
    return bundle_bytes


def validate_model_bundle(bundle_bytes: bytes) -> None:
    if not bundle_bytes:
        raise ValueError("Semantic model bundle is empty.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(bundle_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("Semantic model bundle must be a valid zip archive.") from exc

    with archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if not names:
            raise ValueError("Semantic model bundle does not contain any files.")
        missing: list[str] = []
        if not any(_path_contains_onnx_model(Path(name)) for name in names):
            missing.append("models/onnx/onnx/model.onnx")
        if not any(name.startswith("models/pytorch/") or name.startswith("pytorch/") for name in names):
            missing.append("models/pytorch/")
        for required_file in _REQUIRED_BUNDLE_FILES:
            if required_file not in names:
                missing.append(required_file)
        if missing:
            raise ValueError(
                "Semantic model bundle is missing required artifacts: "
                + ", ".join(sorted(missing))
            )


def create_semantic_model(
    db: Session,
    *,
    slug: str,
    base_model: str,
    artifact_bundle_bytes: bytes,
    embedding_dim: int,
    dataset_id: str | None = None,
    config_json: dict[str, object] | None = None,
    metrics_json: dict[str, object] | None = None,
) -> SemanticModel:
    validate_model_bundle(artifact_bundle_bytes)
    model = SemanticModel(
        slug=slug,
        base_model=base_model,
        status=SEMANTIC_MODEL_STATUS_UPLOADED,
        is_active=False,
        embedding_dim=embedding_dim,
        dataset_id=dataset_id,
        config_json=config_json,
        metrics_json=metrics_json,
    )
    db.add(model)
    db.flush()
    upload_and_record_semantic_model_artifact(
        db,
        model_id=model.id,
        artifact_kind=SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
        content_bytes=artifact_bundle_bytes,
        content_type="application/zip",
        metadata_json={"format": "zip"},
    )
    db.commit()
    db.refresh(model)
    return model


def list_semantic_models(db: Session) -> list[SemanticModel]:
    return list(
        db.scalars(
            select(SemanticModel)
            .options(selectinload(SemanticModel.artifacts))
            .order_by(SemanticModel.created_at.desc(), SemanticModel.id.desc())
        ).all()
    )


def get_semantic_model(db: Session, model_id: str) -> SemanticModel | None:
    return db.scalar(
        select(SemanticModel)
        .options(selectinload(SemanticModel.artifacts))
        .where(SemanticModel.id == model_id)
    )


def get_active_semantic_model_id(db: Session) -> str | None:
    return db.scalar(select(SemanticModel.id).where(SemanticModel.is_active.is_(True)).limit(1))


def count_semantic_model_embeddings(db: Session, model_id: str) -> int:
    return int(
        db.scalar(select(func.count()).select_from(SemanticModelEmbedding).where(SemanticModelEmbedding.model_id == model_id))
        or 0
    )


def count_semantic_model_embeddings_batch(db: Session, model_ids: list[str]) -> dict[str, int]:
    if not model_ids:
        return {}

    rows = db.execute(
        select(SemanticModelEmbedding.model_id, func.count().label("cnt"))
        .where(SemanticModelEmbedding.model_id.in_(model_ids))
        .group_by(SemanticModelEmbedding.model_id)
    ).all()
    counts = {str(row.model_id): int(row.cnt) for row in rows}
    return {model_id: counts.get(model_id, 0) for model_id in model_ids}


def materialize_semantic_model(
    model: SemanticModel,
    *,
    bundle_artifact: SemanticModelArtifact | None = None,
) -> tuple[Path, Path]:
    if bundle_artifact is None:
        with SessionLocal() as db:
            bundle_artifact = get_semantic_model_artifact(
                db,
                model_id=model.id,
                artifact_kind=SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
            )
    if bundle_artifact is None:
        raise ValueError(f"Semantic model {model.id} does not have a registered bundle artifact.")

    base_dir = semantic_temp_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = base_dir / f"semantic-model-{model.id}-{bundle_artifact.sha256[:12]}"
    marker_path = extract_dir / _MODEL_ROOT_MARKER

    if marker_path.exists():
        relative_root = marker_path.read_text(encoding="utf-8").strip()
        model_root = extract_dir / relative_root if relative_root else extract_dir
        if _model_root_has_onnx(model_root):
            return model_root, extract_dir

    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    bundle_bytes = download_artifact_bytes(object_key=bundle_artifact.object_key)
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        archive.extractall(extract_dir)

    model_root = _resolve_extracted_model_root(extract_dir)
    marker_path.write_text(str(model_root.relative_to(extract_dir)), encoding="utf-8")
    return model_root, extract_dir


def _path_contains_onnx_model(path: Path) -> bool:
    parts = path.parts
    return len(parts) >= 2 and parts[-2:] == ("onnx", "model.onnx")


def _model_root_has_onnx(path: Path) -> bool:
    return (path / "onnx" / "model.onnx").exists()


def _resolve_extracted_model_root(extract_dir: Path) -> Path:
    candidates: list[Path] = [extract_dir]
    for child in extract_dir.iterdir():
        if child.is_dir():
            candidates.append(child)
            candidates.extend(gc for gc in child.iterdir() if gc.is_dir())
    for candidate in candidates:
        if _model_root_has_onnx(candidate):
            return candidate
    raise ValueError("Semantic model bundle did not extract to a valid model root.")
