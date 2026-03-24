from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import random
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..core.config import huggingface_cache_dir
from ..core.database import SessionLocal
from ..core.logging_config import setup_loggers
from ..core.models import CardFace
from .text_prep import face_to_text, normalize_oracle_text

setup_loggers()
logger = logging.getLogger("ot_backend.embed.pipeline")

TRAINING_DATASET_FILE_NAME = "training-dataset.json"
CHECKPOINT_DIR_NAME = "checkpoints"
LOG_INTERVAL = 10_000

_DEFAULT_BASE_MODEL: str = os.environ.get("SEMANTIC_BASE_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
_DEFAULT_RUNS_DIR: Path = Path(os.environ.get("SEMANTIC_RUNS_DIR", "data/semantic/runs"))
_DEFAULT_MAX_TAG_PAIRS_PER_TAG = 50
_DEFAULT_MAX_TAG_PAIR_GROUP_SIZE = 2


@dataclass(frozen=True)
class FaceTextRecord:
    id: int
    card_id: str
    name: str
    type_line: str
    oracle_text: str


@dataclass(frozen=True)
class TrainingDatasetState:
    face_texts: dict[int, str]
    pair_ids: list[tuple[int, int]]
    simcse_examples: int
    tag_pair_examples: int


class LazyInputExampleDataset:
    def __init__(self, pair_ids: list[tuple[int, int]], face_texts: dict[int, str], input_example_cls: Any) -> None:
        self._pair_ids = pair_ids
        self._face_texts = face_texts
        self._input_example_cls = input_example_cls

    def __len__(self) -> int:
        return len(self._pair_ids)

    def __getitem__(self, index: int) -> Any:
        left_face_id, right_face_id = self._pair_ids[index]
        return self._input_example_cls(texts=[self._face_texts[left_face_id], self._face_texts[right_face_id]])


@dataclass
class PipelineConfig:
    base_model: str = _DEFAULT_BASE_MODEL
    epochs: int = 5
    batch_size: int = 8
    warmup_divisor: int = 20
    min_warmup_steps: int = 100
    max_tag_pairs_per_tag: int = 50
    max_tag_pair_group_size: int = 2
    skip_fine_tune: bool = False
    skip_embeddings: bool = False
    embed_batch_size: int = 256
    dataset_path: Path | None = None
    run_name: str | None = None
    runs_dir: Path = _DEFAULT_RUNS_DIR

    def to_json(self) -> str:
        d = asdict(self)
        d["dataset_path"] = str(d["dataset_path"]) if d["dataset_path"] else None
        d["runs_dir"] = str(d["runs_dir"])
        return json.dumps(d, indent=2)

    @classmethod
    def from_json_file(cls, path: Path) -> PipelineConfig:
        d: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if d.get("dataset_path"):
            d["dataset_path"] = Path(d["dataset_path"])
        if d.get("runs_dir"):
            d["runs_dir"] = Path(d["runs_dir"])
        return cls(**d)


# ---------------------------------------------------------------------------
# Sentence-transformers / dependency loading
# ---------------------------------------------------------------------------


def _load_sentence_transformers() -> tuple[Any, Any, Any]:
    try:
        st = import_module("sentence_transformers")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "sentence-transformers is required for this pipeline. "
            "Install the semantic-worker extra before running."
        ) from exc
    return getattr(st, "SentenceTransformer"), getattr(st, "InputExample"), getattr(st, "losses")


def _load_sentence_transformer_class() -> Any:
    return _load_sentence_transformers()[0]


def _ensure_training_dependencies() -> None:
    required = {
        "datasets": "The `datasets` package is required.",
        "accelerate": "The `accelerate` package is required.",
    }
    for name, msg in required.items():
        try:
            import_module(name)
        except Exception as exc:  # pragma: no cover - optional dependency guard
            raise RuntimeError(f"{msg} Install the semantic worker dependencies.") from exc


def _is_mps_available() -> bool:
    try:
        torch = import_module("torch")
    except Exception:
        return False
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    return bool(mps is not None and getattr(mps, "is_available", lambda: False)())


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------


def _face_text_records(db: Any) -> list[FaceTextRecord]:
    query = select(CardFace.id, CardFace.card_id, CardFace.name, CardFace.type_line, CardFace.oracle_text).order_by(
        CardFace.id
    )
    rows = db.execute(query)
    return [
        FaceTextRecord(
            id=face_id,
            card_id=card_id,
            name=name or "",
            type_line=type_line or "",
            oracle_text=oracle_text or "",
        )
        for face_id, card_id, name, type_line, oracle_text in rows
    ]


def _normalize_face_record(face: FaceTextRecord) -> str:
    return normalize_oracle_text(text=face.oracle_text, card_name=face.name, type_line=face.type_line)


def build_training_dataset_state(
    db: Any,
    *,
    max_tag_pairs_per_tag: int = _DEFAULT_MAX_TAG_PAIRS_PER_TAG,
    max_tag_pair_group_size: int = _DEFAULT_MAX_TAG_PAIR_GROUP_SIZE,
) -> TrainingDatasetState:
    logger.info("Loading face text for semantic training.")
    face_records = _face_text_records(db)
    face_texts = {face.id: _normalize_face_record(face) for face in face_records}
    card_face_map: dict[str, list[int]] = defaultdict(list)
    for face in face_records:
        card_face_map[face.card_id].append(face.id)

    self_pair_ids = [(face_id, face_id) for face_id, text in face_texts.items() if text.strip()]

    try:
        from ..core.models import CardTagging, Tag
    except Exception as exc:  # pragma: no cover - current branch safety
        raise RuntimeError("Tag models are unavailable in the current codebase state.") from exc

    logger.info("Building tag-derived positive pairs.")
    tag_to_face_ids: dict[str, list[int]] = defaultdict(list)
    direct_oracle_taggings = db.execute(
        select(CardTagging.card_id, Tag.tag_name)
        .join(Tag, CardTagging.tag_id == Tag.id)
        .filter(CardTagging.foreign_key == "oracleId")
        .filter(Tag.tag_namespace == "card")
    )
    for card_id, tag_name in direct_oracle_taggings:
        for fid in card_face_map.get(card_id, []):
            if fid in face_texts:
                tag_to_face_ids[tag_name].append(fid)

    tag_pair_ids: list[tuple[int, int]] = []
    for fids in tag_to_face_ids.values():
        if len(fids) < max_tag_pair_group_size:
            continue
        random.shuffle(fids)
        for a, b in list(zip(fids[::2], fids[1::2]))[:max_tag_pairs_per_tag]:
            if face_texts.get(a) and face_texts.get(b):
                tag_pair_ids.append((a, b))

    pair_ids = self_pair_ids + tag_pair_ids
    random.shuffle(pair_ids)
    return TrainingDatasetState(
        face_texts=face_texts,
        pair_ids=pair_ids,
        simcse_examples=len(self_pair_ids),
        tag_pair_examples=len(tag_pair_ids),
    )


def export_training_dataset(dataset_state: TrainingDatasetState, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "face_texts": [{"id": face_id, "text": text} for face_id, text in sorted(dataset_state.face_texts.items())],
        "pair_ids": [[left, right] for left, right in dataset_state.pair_ids],
        "simcse_examples": dataset_state.simcse_examples,
        "tag_pair_examples": dataset_state.tag_pair_examples,
    }
    output_path.write_text(json.dumps(payload), encoding="utf-8")


def load_training_dataset(input_path: Path) -> TrainingDatasetState:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    face_texts = {int(r["id"]): str(r["text"]) for r in payload["face_texts"]}
    pair_ids = [(int(left), int(right)) for left, right in payload["pair_ids"]]
    return TrainingDatasetState(
        face_texts=face_texts,
        pair_ids=pair_ids,
        simcse_examples=int(payload["simcse_examples"]),
        tag_pair_examples=int(payload["tag_pair_examples"]),
    )


def _prepare_and_save_dataset(output_path: Path, config: PipelineConfig) -> None:
    db = SessionLocal()
    try:
        dataset_state = build_training_dataset_state(
            db,
            max_tag_pairs_per_tag=config.max_tag_pairs_per_tag,
            max_tag_pair_group_size=config.max_tag_pair_group_size,
        )
    finally:
        db.close()
    export_training_dataset(dataset_state, output_path)
    del dataset_state
    gc.collect()
    logger.info("Released in-memory dataset state after export.")


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def _fit_model(model: Any, **kwargs: Any) -> None:
    if _is_mps_available() and hasattr(model, "old_fit"):
        logger.info("Using legacy sentence-transformers training path on MPS.")
        model.old_fit(**kwargs)
        return
    model.fit(**kwargs)


def _train(config: PipelineConfig, dataset_state: TrainingDatasetState, run_dir: Path) -> Any:
    SentenceTransformer, InputExample, losses = _load_sentence_transformers()
    _ensure_training_dependencies()
    cache_dir = huggingface_cache_dir()

    if not dataset_state.pair_ids:
        logger.error("No training examples found; cannot train.")
        raise RuntimeError("No training examples found.")

    checkpoint_path = run_dir / CHECKPOINT_DIR_NAME
    logger.info("Loading base model: %s (cache_dir=%s)", config.base_model, cache_dir)
    model = SentenceTransformer(config.base_model)

    try:
        torch_utils_data = import_module("torch.utils.data")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError("torch is required for training.") from exc
    DataLoader = getattr(torch_utils_data, "DataLoader")

    training_dataset = LazyInputExampleDataset(dataset_state.pair_ids, dataset_state.face_texts, InputExample)
    dataloader = DataLoader(training_dataset, shuffle=False, batch_size=config.batch_size)
    loss = losses.MultipleNegativesRankingLoss(model)

    warmup_steps = max(config.min_warmup_steps, len(training_dataset) // config.warmup_divisor)
    logger.info(
        "Training. examples=%d epochs=%d batch_size=%d warmup_steps=%d",
        len(training_dataset),
        config.epochs,
        config.batch_size,
        warmup_steps,
    )

    checkpoint_path.mkdir(parents=True, exist_ok=True)
    _fit_model(
        model,
        train_objectives=[(dataloader, loss)],
        epochs=config.epochs,
        warmup_steps=warmup_steps,
        show_progress_bar=True,
        checkpoint_path=str(checkpoint_path),
    )
    logger.info("Training complete.")
    return model


# ---------------------------------------------------------------------------
# ONNX export
# ---------------------------------------------------------------------------


def export_onnx_model(model_source: str, output_path: Path) -> None:
    SentenceTransformer = _load_sentence_transformer_class()
    cache_dir = huggingface_cache_dir()
    logger.info(
        "Exporting ONNX model. model_source=%s output_path=%s cache_dir=%s",
        model_source,
        output_path,
        cache_dir,
    )
    model = SentenceTransformer(
        model_source,
        backend="onnx",
        model_kwargs={
            "provider": "CPUExecutionProvider",
            "export": True,
            "file_name": "onnx/model.onnx",
        },
        local_files_only=Path(model_source).exists(),
    )
    output_path.mkdir(parents=True, exist_ok=True)
    model.save(str(output_path))
    logger.info("ONNX model saved to %s", output_path)


# ---------------------------------------------------------------------------
# Embedding computation (uses in-memory PyTorch model — no ONNX reload)
# ---------------------------------------------------------------------------


def _compute_embeddings(model: Any, batch_size: int = 256) -> int:
    try:
        from ..core.models import CardFaceSemanticEmbedding
    except Exception as exc:  # pragma: no cover - current branch safety
        raise RuntimeError("CardFaceSemanticEmbedding model is unavailable.") from exc

    db = SessionLocal()
    try:
        faces = db.query(CardFace).all()
        logger.info("Computing embeddings for %d card faces (batch_size=%d).", len(faces), batch_size)
        db.query(CardFaceSemanticEmbedding).delete()

        if not faces:
            db.commit()
            logger.warning("No faces found; skipped embedding computation.")
            return 0

        texts = [face_to_text(face) for face in faces]
        embeddings = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=True)
        db.add_all(CardFaceSemanticEmbedding(face_id=face.id, embedding=emb) for face, emb in zip(faces, embeddings))

        db.commit()
        logger.info("Stored %d embeddings.", len(faces))
        return len(faces)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Run versioning
# ---------------------------------------------------------------------------


def _make_run_id(run_name: str | None = None) -> str:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    if run_name:
        return f"{timestamp}-{run_name}"
    return timestamp


def _update_latest_symlink(runs_dir: Path, run_dir: Path) -> None:
    latest = runs_dir / "latest"
    latest.unlink(missing_ok=True)
    # Relative symlink so the path stays valid inside Docker mounts
    os.symlink(run_dir.name, latest)
    logger.info("Updated latest: %s -> %s", latest, run_dir.name)


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def run_pipeline(config: PipelineConfig, run_dir: Path) -> int:
    t0 = time.monotonic()
    (run_dir / "config.json").write_text(config.to_json(), encoding="utf-8")
    metrics: dict[str, Any] = {"run_id": run_dir.name, "base_model": config.base_model}

    model: Any = None
    pytorch_path: Path | None = None

    if not config.skip_fine_tune:
        # -- Dataset
        if config.dataset_path:
            dataset_state = load_training_dataset(config.dataset_path)
            logger.info("Loaded pre-exported dataset from %s", config.dataset_path)
        else:
            dataset_path = run_dir / TRAINING_DATASET_FILE_NAME
            _prepare_and_save_dataset(dataset_path, config)
            dataset_state = load_training_dataset(dataset_path)

        metrics["dataset"] = {
            "normalized_faces": len(dataset_state.face_texts),
            "total_examples": len(dataset_state.pair_ids),
            "simcse_examples": dataset_state.simcse_examples,
            "tag_pair_examples": dataset_state.tag_pair_examples,
        }

        # -- Training
        t_train = time.monotonic()
        model = _train(config, dataset_state, run_dir)
        metrics["training_duration_seconds"] = round(time.monotonic() - t_train, 1)

        # -- Compute embeddings while PyTorch model is in memory
        if not config.skip_embeddings:
            metrics["embedding_count"] = _compute_embeddings(model, batch_size=config.embed_batch_size)

        # -- Save PyTorch model
        pytorch_path = run_dir / "pytorch"
        pytorch_path.mkdir(parents=True, exist_ok=True)
        model.save(str(pytorch_path))
        logger.info("PyTorch model saved to %s", pytorch_path)

        # -- Export ONNX from saved PyTorch
        export_onnx_model(str(pytorch_path), run_dir)

    else:
        # No fine-tuning: load base model only for embeddings and ONNX export
        logger.info("Skipping fine-tuning (--no-fine-tune). Using base model: %s", config.base_model)

        if not config.skip_embeddings:
            SentenceTransformer = _load_sentence_transformer_class()
            model = SentenceTransformer(config.base_model)
            metrics["embedding_count"] = _compute_embeddings(model, batch_size=config.embed_batch_size)

        export_onnx_model(config.base_model, run_dir)

    metrics["total_duration_seconds"] = round(time.monotonic() - t0, 1)
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    _update_latest_symlink(config.runs_dir, run_dir)

    logger.info(
        "Pipeline complete. run_id=%s duration=%.1fs",
        run_dir.name,
        metrics["total_duration_seconds"],
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ot_backend.embed.pipeline")
    parser.add_argument("--run-name", help="Label appended to the run ID (e.g. 'larger-batch').")
    parser.add_argument("--epochs", type=int, help="Training epochs (default: 5).")
    parser.add_argument("--batch-size", type=int, help="Training batch size (default: 8).")
    parser.add_argument("--base-model", help="HuggingFace model ID or local path.")
    parser.add_argument("--no-fine-tune", action="store_true", help="Skip training; use base model for embeddings and ONNX export.")
    parser.add_argument("--no-embeddings", action="store_true", help="Skip embedding computation.")
    parser.add_argument("--embed-batch-size", type=int, help="Batch size for embedding computation (default: 256).")
    parser.add_argument("--dataset-path", type=Path, help="Use a pre-exported training dataset JSON.")
    parser.add_argument("--export-dataset", type=Path, help="Export training dataset to JSON and exit.")
    parser.add_argument("--config", type=Path, help="Load PipelineConfig defaults from a JSON file.")
    parser.add_argument("--runs-dir", type=Path, help="Override the runs root directory.")
    parser.add_argument(
        "--reembed-only",
        action="store_true",
        help="Recompute DB embeddings from an existing model without training or touching model files. "
        "Defaults to latest/pytorch; override with --base-model.",
    )
    return parser


def _apply_cli_overrides(config: PipelineConfig, args: argparse.Namespace) -> None:
    if args.run_name is not None:
        config.run_name = args.run_name
    if args.epochs is not None:
        config.epochs = args.epochs
    if args.batch_size is not None:
        config.batch_size = args.batch_size
    if args.base_model is not None:
        config.base_model = args.base_model
    if args.no_fine_tune:
        config.skip_fine_tune = True
    if args.no_embeddings:
        config.skip_embeddings = True
    if args.embed_batch_size is not None:
        config.embed_batch_size = args.embed_batch_size
    if args.dataset_path is not None:
        config.dataset_path = args.dataset_path
    if args.runs_dir is not None:
        config.runs_dir = args.runs_dir


def _reembed(model_source: str, embed_batch_size: int) -> int:
    logger.info("Reembedding from model: %s", model_source)
    SentenceTransformer = _load_sentence_transformer_class()
    model = SentenceTransformer(model_source)
    count = _compute_embeddings(model, batch_size=embed_batch_size)
    logger.info("Reembed complete. embedded=%d", count)
    return 0


def _export_dataset_and_exit(output_path: Path) -> int:
    logger.info("Exporting training dataset to %s", output_path)
    db = SessionLocal()
    try:
        dataset_state = build_training_dataset_state(db)
    finally:
        db.close()
    export_training_dataset(dataset_state, output_path)
    logger.info(
        "Exported dataset. normalized_faces=%d total_examples=%d simcse_examples=%d tag_pair_examples=%d",
        len(dataset_state.face_texts),
        len(dataset_state.pair_ids),
        dataset_state.simcse_examples,
        dataset_state.tag_pair_examples,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv if argv is not None else [])

    if args.export_dataset is not None:
        return _export_dataset_and_exit(args.export_dataset)

    config = PipelineConfig.from_json_file(args.config) if args.config else PipelineConfig()
    _apply_cli_overrides(config, args)

    if args.reembed_only:
        runs_dir = config.runs_dir
        model_source = config.base_model if args.base_model else str(runs_dir / "latest" / "pytorch")
        return _reembed(model_source, embed_batch_size=config.embed_batch_size)

    run_id = _make_run_id(config.run_name)
    run_dir = config.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting pipeline. run_id=%s run_dir=%s", run_id, run_dir)
    return run_pipeline(config, run_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
