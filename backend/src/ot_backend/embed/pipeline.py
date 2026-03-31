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
from sqlalchemy.orm import Session

from ..core.config import huggingface_cache_dir
from ..core.database import SessionLocal
from ..core.logging_config import setup_loggers
from ..core.models import CardFace
from .query_gen import generate_template_queries
from .text_prep import face_to_text, normalize_oracle_text

logger = logging.getLogger("ot_backend.embed.pipeline")

TRAINING_DATASET_FILE_NAME = "training-dataset.json"
CHECKPOINT_DIR_NAME = "checkpoints"
LOG_INTERVAL = 10_000

_DEFAULT_BASE_MODEL: str = os.environ.get("SEMANTIC_BASE_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
_DEFAULT_RUNS_DIR: Path = Path(os.environ.get("SEMANTIC_RUNS_DIR", "data/semantic/runs"))
_DEFAULT_MAX_TAG_PAIRS_PER_TAG = 50
_DEFAULT_MAX_TAG_PAIR_GROUP_SIZE = 5
_DEFAULT_MAX_TAG_DESC_PAIRS_PER_TAG = 50
FaceIdentity = tuple[str, int]


@dataclass(frozen=True)
class FaceTextRecord:
    oracle_id: str
    face_ix: int
    name: str
    type_line: str
    oracle_text: str


@dataclass(frozen=True)
class TrainingDatasetState:
    face_texts: dict[FaceIdentity, str]
    pair_ids: list[tuple[FaceIdentity, FaceIdentity]]
    direct_text_pairs: list[tuple[str, str]]
    simcse_examples: int
    tag_pair_examples: int
    tag_desc_pair_examples: int
    template_query_examples: int = 0


class LazyInputExampleDataset:
    def __init__(
        self,
        pair_ids: list[tuple[FaceIdentity, FaceIdentity]],
        face_texts: dict[FaceIdentity, str],
        input_example_cls: Any,
        direct_text_pairs: list[tuple[str, str]] | None = None,
    ) -> None:
        self._pair_ids = pair_ids
        self._face_texts = face_texts
        self._input_example_cls = input_example_cls
        self._direct_text_pairs = direct_text_pairs or []
        self._id_pair_count = len(pair_ids)

    def __len__(self) -> int:
        return self._id_pair_count + len(self._direct_text_pairs)

    def __getitem__(self, index: int) -> Any:
        if index < self._id_pair_count:
            left_face_key, right_face_key = self._pair_ids[index]
            return self._input_example_cls(
                texts=[self._face_texts[left_face_key], self._face_texts[right_face_key]]
            )
        else:
            anchor, positive = self._direct_text_pairs[index - self._id_pair_count]
            return self._input_example_cls(texts=[anchor, positive])


@dataclass
class PipelineConfig:
    base_model: str = _DEFAULT_BASE_MODEL
    epochs: int = 5
    batch_size: int = 8
    warmup_divisor: int = 20
    min_warmup_steps: int = 100
    max_tag_pairs_per_tag: int = 50
    max_tag_pair_group_size: int = 5
    max_tag_desc_pairs_per_tag: int = 50
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


def _face_text_records(db: Session) -> list[FaceTextRecord]:
    query = select(
        CardFace.oracle_id,
        CardFace.face_ix,
        CardFace.name,
        CardFace.type_line,
        CardFace.oracle_text,
    ).order_by(CardFace.oracle_id, CardFace.face_ix)
    rows = db.execute(query)
    return [
        FaceTextRecord(
            oracle_id=oracle_id,
            face_ix=face_ix,
            name=name or "",
            type_line=type_line or "",
            oracle_text=oracle_text or "",
        )
        for oracle_id, face_ix, name, type_line, oracle_text in rows
    ]


def _normalize_face_record(face: FaceTextRecord) -> str:
    return normalize_oracle_text(text=face.oracle_text, card_name=face.name, type_line=face.type_line)


def build_training_dataset_state(
    db: Session,
    *,
    max_tag_pairs_per_tag: int = _DEFAULT_MAX_TAG_PAIRS_PER_TAG,
    max_tag_pair_group_size: int = _DEFAULT_MAX_TAG_PAIR_GROUP_SIZE,
    max_tag_desc_pairs_per_tag: int = _DEFAULT_MAX_TAG_DESC_PAIRS_PER_TAG,
) -> TrainingDatasetState:
    logger.info("Loading face text for semantic training.")
    face_records = _face_text_records(db)
    face_texts = {(face.oracle_id, face.face_ix): _normalize_face_record(face) for face in face_records}
    card_face_map: dict[str, list[FaceIdentity]] = defaultdict(list)
    for face in face_records:
        card_face_map[face.oracle_id].append((face.oracle_id, face.face_ix))

    self_pair_ids = [(face_key, face_key) for face_key, text in face_texts.items() if text.strip()]

    try:
        from ..core.models import CardTagging, Tag
    except Exception as exc:  # pragma: no cover - current branch safety
        raise RuntimeError("Tag models are unavailable in the current codebase state.") from exc

    logger.info("Building tag-derived positive pairs.")
    tag_to_face_ids: dict[str, list[FaceIdentity]] = defaultdict(list)
    tag_to_desc: dict[str, str] = {}
    tag_to_desc_faces: dict[str, list[FaceIdentity]] = defaultdict(list)

    direct_oracle_taggings = db.execute(
        select(CardTagging.card_id, Tag.tag_name, Tag.tag_description)
        .join(Tag, CardTagging.tag_id == Tag.id)
        .filter(CardTagging.foreign_key == "oracleId")
        .filter(Tag.tag_namespace == "card")
    )
    for card_id, tag_name, tag_description in direct_oracle_taggings:
        face_keys = [fk for fk in card_face_map.get(card_id, []) if fk in face_texts]
        for face_key in face_keys:
            tag_to_face_ids[tag_name].append(face_key)
        normalized_name = tag_name.replace("-", " ").replace("_", " ")
        anchor = f"{normalized_name}. {tag_description}".strip() if tag_description else normalized_name
        tag_to_desc[tag_name] = anchor
        for face_key in face_keys:
            tag_to_desc_faces[tag_name].append(face_key)

    tag_pair_ids: list[tuple[FaceIdentity, FaceIdentity]] = []
    for fids in tag_to_face_ids.values():
        if len(fids) < max_tag_pair_group_size:
            continue
        random.shuffle(fids)
        for a, b in list(zip(fids[::2], fids[1::2]))[:max_tag_pairs_per_tag]:
            if a[0] != b[0] and face_texts.get(a) and face_texts.get(b):
                tag_pair_ids.append((a, b))

    logger.info("Building tag-description anchor pairs.")
    direct_text_pairs: list[tuple[str, str]] = []
    for tag_name, face_ids in tag_to_desc_faces.items():
        if not face_ids:
            continue
        anchor = tag_to_desc[tag_name]
        sampled = random.sample(face_ids, min(len(face_ids), max_tag_desc_pairs_per_tag))
        for face_key in sampled:
            direct_text_pairs.append((anchor, face_texts[face_key]))

    logger.info("Building template query pairs.")
    template_query_examples = 0
    for face_key, oracle_text in face_texts.items():
        for query in generate_template_queries(oracle_text):
            direct_text_pairs.append((query, oracle_text))
            template_query_examples += 1
    logger.info("Template query pairs built. count=%d", template_query_examples)

    pair_ids = self_pair_ids + tag_pair_ids
    random.shuffle(pair_ids)
    random.shuffle(direct_text_pairs)
    tag_desc_count = len(direct_text_pairs) - template_query_examples
    return TrainingDatasetState(
        face_texts=face_texts,
        pair_ids=pair_ids,
        direct_text_pairs=direct_text_pairs,
        simcse_examples=len(self_pair_ids),
        tag_pair_examples=len(tag_pair_ids),
        tag_desc_pair_examples=tag_desc_count,
        template_query_examples=template_query_examples,
    )


TRAINING_DATASET_VERSION = 4


def export_training_dataset(dataset_state: TrainingDatasetState, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": TRAINING_DATASET_VERSION,
        "face_texts": [
            {"oracle_id": oracle_id, "face_ix": face_ix, "text": text}
            for (oracle_id, face_ix), text in sorted(dataset_state.face_texts.items())
        ],
        "pair_ids": [
            [[left_oracle_id, left_face_ix], [right_oracle_id, right_face_ix]]
            for (left_oracle_id, left_face_ix), (right_oracle_id, right_face_ix) in dataset_state.pair_ids
        ],
        "direct_text_pairs": list(dataset_state.direct_text_pairs),
        "simcse_examples": dataset_state.simcse_examples,
        "tag_pair_examples": dataset_state.tag_pair_examples,
        "tag_desc_pair_examples": dataset_state.tag_desc_pair_examples,
        "template_query_examples": dataset_state.template_query_examples,
    }
    output_path.write_text(json.dumps(payload), encoding="utf-8")


def load_training_dataset(input_path: Path) -> TrainingDatasetState:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    version = int(payload["version"])
    if version not in (2, 3, 4):
        raise ValueError(f"Unsupported training dataset format version: {version}.")
    face_texts = {
        (str(r["oracle_id"]), int(r["face_ix"])): str(r["text"])
        for r in payload["face_texts"]
    }
    pair_ids = [
        ((str(left_oracle_id), int(left_face_ix)), (str(right_oracle_id), int(right_face_ix)))
        for [left_oracle_id, left_face_ix], [right_oracle_id, right_face_ix] in payload["pair_ids"]
    ]
    direct_text_pairs: list[tuple[str, str]] = [
        (str(a), str(b)) for a, b in payload.get("direct_text_pairs", [])
    ]
    return TrainingDatasetState(
        face_texts=face_texts,
        pair_ids=pair_ids,
        direct_text_pairs=direct_text_pairs,
        simcse_examples=int(payload["simcse_examples"]),
        tag_pair_examples=int(payload["tag_pair_examples"]),
        tag_desc_pair_examples=int(payload.get("tag_desc_pair_examples", 0)),
        template_query_examples=int(payload.get("template_query_examples", 0)),
    )


def _prepare_and_save_dataset(output_path: Path, config: PipelineConfig) -> None:
    db = SessionLocal()
    try:
        dataset_state = build_training_dataset_state(
            db,
            max_tag_pairs_per_tag=config.max_tag_pairs_per_tag,
            max_tag_pair_group_size=config.max_tag_pair_group_size,
            max_tag_desc_pairs_per_tag=config.max_tag_desc_pairs_per_tag,
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

    training_dataset = LazyInputExampleDataset(
        dataset_state.pair_ids,
        dataset_state.face_texts,
        InputExample,
        direct_text_pairs=dataset_state.direct_text_pairs,
    )
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
        db.add_all(
            CardFaceSemanticEmbedding(oracle_id=face.oracle_id, face_ix=face.face_ix, embedding=emb)
            for face, emb in zip(faces, embeddings)
        )

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
            "total_examples": len(dataset_state.pair_ids) + len(dataset_state.direct_text_pairs),
            "simcse_examples": dataset_state.simcse_examples,
            "tag_pair_examples": dataset_state.tag_pair_examples,
            "tag_desc_pair_examples": dataset_state.tag_desc_pair_examples,
            "template_query_examples": dataset_state.template_query_examples,
        }

        # -- Training
        t_train = time.monotonic()
        model = _train(config, dataset_state, run_dir)
        metrics["training_duration_seconds"] = round(time.monotonic() - t_train, 1)

        # -- Compute embeddings while PyTorch model is in memory
        if not config.skip_embeddings:
            metrics["embedding_count"] = _compute_embeddings(model, batch_size=config.embed_batch_size)

        # -- Save PyTorch model
        pytorch_path = run_dir / "models" / "pytorch"
        pytorch_path.mkdir(parents=True, exist_ok=True)
        model.save(str(pytorch_path))
        logger.info("PyTorch model saved to %s", pytorch_path)

        # -- Export ONNX from saved PyTorch
        export_onnx_model(str(pytorch_path), run_dir / "models" / "onnx")

    else:
        # No fine-tuning: load base model only for embeddings and ONNX export
        logger.info("Skipping fine-tuning (--no-fine-tune). Using base model: %s", config.base_model)

        if not config.skip_embeddings:
            SentenceTransformer = _load_sentence_transformer_class()
            model = SentenceTransformer(config.base_model)
            metrics["embedding_count"] = _compute_embeddings(model, batch_size=config.embed_batch_size)

        export_onnx_model(config.base_model, run_dir / "models" / "onnx")

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
    parser.add_argument("--max-tag-desc-pairs-per-tag", type=int, help="Max tag-description anchor pairs per tag (default: 20).")
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
    parser.add_argument(
        "--load-embeddings",
        nargs="?",
        const="latest",
        default=None,
        metavar="PATH",
        help="Load pre-computed embeddings from a .npz file into DB. "
        "Omit the path to use the latest run (runs/latest/embeddings/embeddings.npz).",
    )
    parser.add_argument(
        "--eval",
        nargs="?",
        const=str(_DEFAULT_EVAL_PATH),
        default=None,
        metavar="PATH",
        help="Run eval queries against the latest run's embeddings and print ranked results. "
        "Omit the path to use scripts/eval_queries.json.",
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
    if args.max_tag_desc_pairs_per_tag is not None:
        config.max_tag_desc_pairs_per_tag = args.max_tag_desc_pairs_per_tag
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


def _load_embeddings_from_file(path: Path) -> int:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required to load pre-computed embeddings.") from exc

    try:
        from ..core.models import CardFaceSemanticEmbedding
    except Exception as exc:
        raise RuntimeError("CardFaceSemanticEmbedding model is unavailable.") from exc

    logger.info("Loading pre-computed embeddings from %s", path)
    data = np.load(path, allow_pickle=False)
    oracle_ids: list[str] = data["oracle_ids"].tolist()
    face_ixs: list[int] = data["face_ixs"].tolist()
    embeddings = data["embeddings"]

    db = SessionLocal()
    try:
        db.query(CardFaceSemanticEmbedding).delete()
        db.add_all(
            CardFaceSemanticEmbedding(
                oracle_id=oracle_ids[i],
                face_ix=face_ixs[i],
                embedding=embeddings[i].tolist(),
            )
            for i in range(len(oracle_ids))
        )
        db.commit()
        logger.info("Stored %d embeddings from file.", len(oracle_ids))
        return len(oracle_ids)
    finally:
        db.close()


_DEFAULT_EVAL_PATH = Path(__file__).parents[4] / "scripts" / "eval_queries.json"
_EVAL_TOP_K = 5
_EVAL_TEXT_PREVIEW = 90


def _run_eval(runs_dir: Path, model_source: str | None, eval_path: Path) -> int:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for eval.") from exc

    if not eval_path.exists():
        raise FileNotFoundError(f"Eval queries file not found: {eval_path}")

    latest = runs_dir / "latest"
    npz_path = latest / "embeddings" / "embeddings.npz"
    dataset_path = latest / TRAINING_DATASET_FILE_NAME

    if not npz_path.exists():
        raise FileNotFoundError(
            f"Embeddings not found at {npz_path}\n"
            "Run the pipeline first to produce embeddings."
        )
    if not dataset_path.exists():
        raise FileNotFoundError(f"Training dataset not found at {dataset_path}")

    resolved_model = model_source or str(latest / "models" / "pytorch")
    logger.info("Loading model from %s", resolved_model)
    SentenceTransformer = _load_sentence_transformer_class()
    model = SentenceTransformer(resolved_model)

    logger.info("Loading embeddings from %s", npz_path)
    data = np.load(npz_path, allow_pickle=False)
    oracle_ids: list[str] = data["oracle_ids"].tolist()
    face_ixs: list[int] = data["face_ixs"].tolist()
    embeddings: np.ndarray = data["embeddings"]  # (N, D), already L2-normalized

    logger.info("Loading face texts from %s", dataset_path)
    dataset_state = load_training_dataset(dataset_path)
    face_texts = dataset_state.face_texts

    import json as _json
    queries = _json.loads(eval_path.read_text(encoding="utf-8"))["queries"]
    logger.info("Running eval. queries=%d top_k=%d", len(queries), _EVAL_TOP_K)

    for item in queries:
        query: str = item["query"]
        expected: list[str] = item.get("expected_cards", [])
        notes: str = item.get("notes", "")

        query_emb = model.encode(
            [query], normalize_embeddings=True, show_progress_bar=False
        )[0]
        scores: np.ndarray = embeddings @ query_emb
        top_indices = scores.argsort()[::-1][:_EVAL_TOP_K]

        print(f"\n{'─' * 72}")
        print(f"Query : {query!r}")
        if notes:
            print(f"Notes : {notes}")
        if expected:
            print(f"Expect: {', '.join(expected[:4])}")
        print("Results:")
        for rank, idx in enumerate(top_indices, 1):
            oid = oracle_ids[idx]
            fix = face_ixs[idx]
            score = float(scores[idx])
            text = face_texts.get((oid, fix), "")[:_EVAL_TEXT_PREVIEW].replace("\n", " ")
            print(f"  {rank}. [{score:.3f}] {oid[:8]}… | {text}")

    print(f"\n{'─' * 72}")
    logger.info("Eval complete.")
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
        "Exported dataset. normalized_faces=%d total_examples=%d simcse_examples=%d tag_pair_examples=%d tag_desc_pair_examples=%d template_query_examples=%d",
        len(dataset_state.face_texts),
        len(dataset_state.pair_ids) + len(dataset_state.direct_text_pairs),
        dataset_state.simcse_examples,
        dataset_state.tag_pair_examples,
        dataset_state.tag_desc_pair_examples,
        dataset_state.template_query_examples,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_loggers()
    args = _build_parser().parse_args(argv if argv is not None else [])

    if args.export_dataset is not None:
        return _export_dataset_and_exit(args.export_dataset)

    if args.load_embeddings is not None:
        if args.load_embeddings == "latest":
            embeddings_path = _DEFAULT_RUNS_DIR / "latest" / "embeddings" / "embeddings.npz"
        else:
            embeddings_path = Path(args.load_embeddings)
        count = _load_embeddings_from_file(embeddings_path)
        logger.info("load-embeddings complete. stored=%d", count)
        return 0

    config = PipelineConfig.from_json_file(args.config) if args.config else PipelineConfig()
    _apply_cli_overrides(config, args)

    if args.eval is not None:
        return _run_eval(
            runs_dir=config.runs_dir,
            model_source=config.base_model if args.base_model else None,
            eval_path=Path(args.eval),
        )

    if args.reembed_only:
        runs_dir = config.runs_dir
        model_source = config.base_model if args.base_model else str(runs_dir / "latest" / "models" / "pytorch")
        return _reembed(model_source, embed_batch_size=config.embed_batch_size)

    run_id = _make_run_id(config.run_name)
    run_dir = config.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting pipeline. run_id=%s run_dir=%s", run_id, run_dir)
    return run_pipeline(config, run_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
