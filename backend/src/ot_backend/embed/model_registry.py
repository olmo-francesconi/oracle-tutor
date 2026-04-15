from __future__ import annotations

import io
import json
import logging
import shutil
import zipfile
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..core.config import semantic_temp_dir
from ..core.database import SessionLocal
from ..core.models import CardFace, SemanticModel, SemanticModelEmbedding
from .artifacts import (
    SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
    SemanticModelArtifact,
    download_artifact_bytes,
    get_semantic_model_artifact,
    upload_and_record_semantic_model_artifact,
)
from .semantic_state import get_semantic_data_version, record_active_model_data_version
from .text_prep import normalize_oracle_text

logger = logging.getLogger("ot_backend.embed.registry")

SEMANTIC_MODEL_STATUS_UPLOADED = "uploaded"
SEMANTIC_MODEL_STATUS_EMBEDDING = "embedding"
SEMANTIC_MODEL_STATUS_READY = "ready"
SEMANTIC_MODEL_STATUS_ACTIVE = "active"
SEMANTIC_MODEL_STATUS_FAILED = "failed"
SEMANTIC_MODEL_STATUS_ARCHIVED = "archived"
_MODEL_ROOT_MARKER = ".model_root"
_PROMOTION_ADVISORY_LOCK_KEY = 7391824650182736
_DEFAULT_REEMBED_BATCH_SIZE = 64
SEMANTIC_MODEL_CONFIG_DATASET_METADATA = "dataset_metadata"
SEMANTIC_MODEL_CONFIG_SOURCE_DATA_VERSION = "semantic_data_version"
_EMBEDDINGS_ARCHIVE_RELATIVE_PATH = Path("embeddings") / "embeddings.npz"
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
    return db.scalars(
        select(SemanticModel)
        .options(selectinload(SemanticModel.artifacts))
        .order_by(SemanticModel.created_at.desc(), SemanticModel.id.desc())
    ).all()


def get_semantic_model(db: Session, model_id: str) -> SemanticModel | None:
    return db.scalar(
        select(SemanticModel)
        .options(selectinload(SemanticModel.artifacts))
        .where(SemanticModel.id == model_id)
    )


def get_active_semantic_model(db: Session) -> SemanticModel | None:
    return db.scalars(select(SemanticModel).where(SemanticModel.is_active.is_(True)).limit(1)).first()


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


def _try_promotion_advisory_lock(db: Session) -> bool:
    if db.bind is None or db.bind.dialect.name != "postgresql":  # type: ignore[union-attr]
        return True
    return bool(db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _PROMOTION_ADVISORY_LOCK_KEY}))


def begin_semantic_model_promotion(model_id: str) -> SemanticModel:
    with SessionLocal() as db:
        lock_acquired = _try_promotion_advisory_lock(db)
        if not lock_acquired:
            raise RuntimeError("Another semantic model promotion is already running.")

        model = db.get(SemanticModel, model_id)
        if model is None:
            raise KeyError(f"Semantic model {model_id} not found.")
        if model.is_active and model.status == SEMANTIC_MODEL_STATUS_ACTIVE:
            raise ValueError(f"Semantic model {model_id} is already active.")
        if model.status == SEMANTIC_MODEL_STATUS_EMBEDDING:
            raise RuntimeError(f"Semantic model {model_id} promotion is already in progress.")
        model.status = SEMANTIC_MODEL_STATUS_EMBEDDING
        model.error_message = None
        merged_metrics = dict(model.metrics_json or {})
        merged_metrics["promotion_started_at"] = datetime.now(UTC).isoformat()
        model.metrics_json = merged_metrics
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise RuntimeError("Another semantic model promotion is already running.") from exc
        db.refresh(model)
        return model


def run_semantic_model_promotion(model_id: str, *, embed_batch_size: int = _DEFAULT_REEMBED_BATCH_SIZE) -> bool:
    try:
        with SessionLocal() as db:
            lock_acquired = _try_promotion_advisory_lock(db)
            if not lock_acquired:
                raise RuntimeError("Another semantic model promotion is already running.")

            model = db.get(SemanticModel, model_id)
            if model is None:
                raise KeyError(f"Semantic model {model_id} not found.")
            if model.status != SEMANTIC_MODEL_STATUS_EMBEDDING:
                raise RuntimeError(
                    f"Semantic model {model_id} must be in '{SEMANTIC_MODEL_STATUS_EMBEDDING}' status before promotion runs."
                )
            _ensure_model_is_not_stale(db, model)
            model_root, bundle_root = materialize_semantic_model(model)

        embedding_count, embedding_backend = _populate_model_embeddings(
            model_id,
            model_root,
            bundle_root,
            batch_size=embed_batch_size,
        )
        _activate_model(model_id, embedding_count=embedding_count, embedding_backend=embedding_backend)

        try:
            from .index import mark_semantic_index_stale

            mark_semantic_index_stale()
        except Exception:
            logger.exception("Failed to mark semantic index cache stale after activation.")
        return True
    except Exception as exc:
        logger.exception("Semantic model promotion failed for model_id=%s", model_id)
        _mark_model_failed(model_id, str(exc))
        _clear_model_embeddings(model_id)
        return False


def _path_contains_onnx_model(path: Path) -> bool:
    parts = path.parts
    if len(parts) >= 2 and parts[-2:] == ("onnx", "model.onnx"):
        return True
    return path.name == "model.onnx"


def _model_root_has_onnx(path: Path) -> bool:
    return (path / "onnx" / "model.onnx").exists() or (path / "model.onnx").exists()


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


def _iter_face_rows(batch_size: int) -> Iterator[list[tuple[str, int, str]]]:
    effective_batch_size = max(1, batch_size)
    with SessionLocal() as db:
        rows = db.execute(
            select(
                CardFace.oracle_id,
                CardFace.face_ix,
                CardFace.name,
                CardFace.type_line,
                CardFace.oracle_text,
            ).order_by(CardFace.oracle_id, CardFace.face_ix)
        )
        while True:
            chunk = rows.fetchmany(effective_batch_size)
            if not chunk:
                return
            yield [
                (
                    oracle_id,
                    face_ix,
                    normalize_oracle_text(text=oracle_text or "", card_name=name or "", type_line=type_line or ""),
                )
                for oracle_id, face_ix, name, type_line, oracle_text in chunk
            ]


def _resolve_embeddings_archive_path(bundle_root: Path) -> Path | None:
    candidate = bundle_root / _EMBEDDINGS_ARCHIVE_RELATIVE_PATH
    return candidate if candidate.exists() else None


def _resolve_pytorch_model_path(bundle_root: Path) -> Path | None:
    for candidate in (bundle_root / "models" / "pytorch", bundle_root / "pytorch"):
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _store_model_embeddings_batches(
    model_id: str,
    row_batches: Iterable[list[tuple[str, int, list[float]]]],
) -> int:
    total = 0
    with SessionLocal() as db:
        db.query(SemanticModelEmbedding).filter(SemanticModelEmbedding.model_id == model_id).delete()
        db.commit()
        for rows in row_batches:
            if not rows:
                continue
            db.add_all(
                SemanticModelEmbedding(
                    model_id=model_id,
                    oracle_id=oracle_id,
                    face_ix=face_ix,
                    embedding=embedding,
                )
                for oracle_id, face_ix, embedding in rows
            )
            db.commit()
            total += len(rows)
    return total


def _store_model_embeddings(model_id: str, rows: list[tuple[str, int, list[float]]]) -> int:
    return _store_model_embeddings_batches(model_id, [rows])


def _load_sentence_transformer_class():
    try:
        st = import_module("sentence_transformers")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "sentence-transformers is required for semantic model promotion. "
            "Install the semantic worker dependencies."
        ) from exc
    return getattr(st, "SentenceTransformer")


def _store_precomputed_embeddings_from_archive(model_id: str, archive_path: Path, *, batch_size: int) -> int:
    logger.info("Loading precomputed semantic embeddings from %s", archive_path)
    with np.load(archive_path, allow_pickle=False) as archive:
        oracle_ids = archive["oracle_ids"]
        face_ixs = archive["face_ixs"]
        embeddings = np.asarray(archive["embeddings"], dtype=np.float32)

        if len(oracle_ids) != len(face_ixs) or len(oracle_ids) != len(embeddings):
            raise RuntimeError(
                f"Precomputed embeddings archive {archive_path} has inconsistent lengths: "
                f"oracle_ids={len(oracle_ids)} face_ixs={len(face_ixs)} embeddings={len(embeddings)}."
            )

        def iter_batches() -> Iterator[list[tuple[str, int, list[float]]]]:
            step = max(1, batch_size)
            for start in range(0, len(oracle_ids), step):
                end = min(start + step, len(oracle_ids))
                yield [
                    (
                        str(oracle_ids[idx]),
                        int(face_ixs[idx]),
                        np.asarray(embeddings[idx], dtype=np.float32).tolist(),
                    )
                    for idx in range(start, end)
                ]

        count = _store_model_embeddings_batches(model_id, iter_batches())
        logger.info("Loaded precomputed embeddings. faces=%d", count)
        return count


def _compute_and_store_embeddings_from_pytorch_model(model_id: str, model_path: Path, *, batch_size: int) -> int:
    SentenceTransformer = _load_sentence_transformer_class()
    logger.info("Computing semantic embeddings with PyTorch model at %s (batch_size=%d)", model_path, batch_size)
    model = SentenceTransformer(str(model_path), local_files_only=True)

    def iter_batches() -> Iterator[list[tuple[str, int, list[float]]]]:
        for face_rows in _iter_face_rows(batch_size):
            texts = [text for _, _, text in face_rows]
            vectors = np.asarray(
                model.encode(
                    texts,
                    batch_size=max(1, batch_size),
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ),
                dtype=np.float32,
            )
            yield [
                (
                    oracle_id,
                    face_ix,
                    np.asarray(vectors[idx], dtype=np.float32).tolist(),
                )
                for idx, (oracle_id, face_ix, _text) in enumerate(face_rows)
            ]

    count = _store_model_embeddings_batches(model_id, iter_batches())
    logger.info("PyTorch embedding complete. faces=%d", count)
    return count


def _compute_and_store_embeddings_from_onnx_model(model_id: str, model_root: Path, *, batch_size: int) -> int:
    from .index import OnnxTextEncoder

    logger.info("Computing semantic embeddings with ONNX model at %s (batch_size=%d)", model_root, batch_size)
    encoder = OnnxTextEncoder(model_root=model_root)

    def iter_batches() -> Iterator[list[tuple[str, int, list[float]]]]:
        for face_rows in _iter_face_rows(batch_size):
            texts = [text for _, _, text in face_rows]
            vectors = encoder.encode_many(texts, batch_size=max(1, batch_size), normalize_inputs=False)
            yield [
                (oracle_id, face_ix, vectors[idx])
                for idx, (oracle_id, face_ix, _text) in enumerate(face_rows)
            ]

    count = _store_model_embeddings_batches(model_id, iter_batches())
    logger.info("ONNX embedding complete. faces=%d", count)
    return count


def _populate_model_embeddings(model_id: str, model_root: Path, bundle_root: Path, *, batch_size: int) -> tuple[int, str]:
    archive_path = _resolve_embeddings_archive_path(bundle_root)
    if archive_path is not None:
        return _store_precomputed_embeddings_from_archive(model_id, archive_path, batch_size=batch_size), "precomputed"

    pytorch_model_path = _resolve_pytorch_model_path(bundle_root)
    if pytorch_model_path is not None:
        return (
            _compute_and_store_embeddings_from_pytorch_model(
                model_id,
                pytorch_model_path,
                batch_size=batch_size,
            ),
            "pytorch",
        )

    return _compute_and_store_embeddings_from_onnx_model(model_id, model_root, batch_size=batch_size), "onnx"


def _activate_model(model_id: str, *, embedding_count: int, embedding_backend: str | None = None) -> None:
    activated_at = datetime.now(UTC).replace(tzinfo=None)
    with SessionLocal() as db:
        db.query(SemanticModel).filter(SemanticModel.is_active.is_(True), SemanticModel.id != model_id).update(
            {
                SemanticModel.is_active: False,
                SemanticModel.status: SEMANTIC_MODEL_STATUS_READY,
            },
            synchronize_session=False,
        )
        model = db.get(SemanticModel, model_id)
        if model is None:
            raise KeyError(f"Semantic model {model_id} not found during activation.")

        merged_metrics = dict(model.metrics_json or {})
        merged_metrics["embedding_count"] = embedding_count
        merged_metrics["promotion_completed_at"] = datetime.now(UTC).isoformat()
        if embedding_backend is not None:
            merged_metrics["promotion_embedding_backend"] = embedding_backend

        model.status = SEMANTIC_MODEL_STATUS_ACTIVE
        model.is_active = True
        model.activated_at = activated_at
        model.error_message = None
        model.metrics_json = merged_metrics
        db.commit()
        semantic_data_version = _get_model_source_data_version(model)
        if semantic_data_version is not None:
            record_active_model_data_version(db, semantic_data_version)


def _mark_model_failed(model_id: str, error_message: str) -> None:
    with SessionLocal() as db:
        model = db.get(SemanticModel, model_id)
        if model is None:
            return
        model.status = SEMANTIC_MODEL_STATUS_FAILED
        model.error_message = error_message[:4000]
        model.is_active = False
        db.commit()


def _clear_model_embeddings(model_id: str) -> None:
    with SessionLocal() as db:
        db.query(SemanticModelEmbedding).filter(SemanticModelEmbedding.model_id == model_id).delete()
        db.commit()


def _get_model_source_data_version(model: SemanticModel) -> int | None:
    config = model.config_json or {}
    raw_value = config.get(SEMANTIC_MODEL_CONFIG_SOURCE_DATA_VERSION)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str) and raw_value.isdigit():
        return int(raw_value)

    dataset_metadata = config.get(SEMANTIC_MODEL_CONFIG_DATASET_METADATA)
    if isinstance(dataset_metadata, dict):
        fallback = dataset_metadata.get(SEMANTIC_MODEL_CONFIG_SOURCE_DATA_VERSION)
        if isinstance(fallback, int):
            return fallback
        if isinstance(fallback, str) and fallback.isdigit():
            return int(fallback)
    return None


def _ensure_model_is_not_stale(db: Session, model: SemanticModel) -> None:
    source_version = _get_model_source_data_version(model)
    current_version = get_semantic_data_version(db)

    if source_version is None and current_version == 0:
        # Neither the model nor the DB has a data version yet — no data ingested, can't be stale.
        return
    if source_version is None:
        raise RuntimeError(
            f"Semantic model {model.id} has no source semantic data version recorded. "
            "Promotion blocked to prevent promoting against stale data."
        )

    if current_version and current_version != source_version:
        raise RuntimeError(
            f"Semantic model {model.id} is stale: source semantic data version {source_version} "
            f"does not match current version {current_version}."
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
