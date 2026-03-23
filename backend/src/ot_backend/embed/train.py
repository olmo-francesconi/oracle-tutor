from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..core.config import huggingface_cache_dir, semantic_model_path
from ..core.database import SessionLocal
from ..core.models import CardFace
from .text_prep import normalize_oracle_text

logger = logging.getLogger("ot_backend.embed.train")

BASE_MODEL_NAME = os.environ.get("SEMANTIC_BASE_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
BATCH_SIZE = 8
EPOCHS = 5
MIN_WARMUP_STEPS = 100
WARMUP_DIVISOR = 20
MAX_TAG_PAIRS_PER_TAG = 50
MAX_TAG_PAIR_GROUP_SIZE = 2
CHECKPOINT_DIR_NAME = "checkpoints"
TRAINING_DATASET_FILE_NAME = "training-dataset.json"


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


def _load_sentence_transformers() -> tuple[Any, Any, Any]:
    try:
        sentence_transformers = import_module("sentence_transformers")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "sentence-transformers is required for semantic training. "
            "Install the optional semantic extra before running this module."
        ) from exc
    return (
        getattr(sentence_transformers, "SentenceTransformer"),
        getattr(sentence_transformers, "InputExample"),
        getattr(sentence_transformers, "losses"),
    )


def _load_sentence_transformer_class() -> Any:
    return _load_sentence_transformers()[0]


def _ensure_training_dependencies() -> None:
    required_modules = {
        "datasets": "The `datasets` package is required for semantic training.",
        "accelerate": "The `accelerate` package is required for semantic training.",
    }
    for module_name, message in required_modules.items():
        try:
            import_module(module_name)
        except Exception as exc:  # pragma: no cover - optional dependency guard
            raise RuntimeError(
                f"{message} Install the semantic worker dependencies before running this module."
            ) from exc


def _is_mps_available() -> bool:
    try:
        torch = import_module("torch")
    except Exception:
        return False

    mps = getattr(getattr(torch, "backends", None), "mps", None)
    return bool(mps is not None and getattr(mps, "is_available", lambda: False)())


def _training_output_path(path_override: str | None = None) -> Path:
    if path_override:
        return Path(path_override)
    return semantic_model_path()


def export_onnx_model(model_source: str, output_path: Path) -> None:
    SentenceTransformer = _load_sentence_transformer_class()
    cache_dir = huggingface_cache_dir()
    logger.info(
        "Exporting ONNX semantic model. model_source=%s output_path=%s cache_dir=%s",
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
    logger.info("Exported ONNX semantic model to %s", output_path)


def _fit_model(model: Any, **kwargs: Any) -> None:
    if _is_mps_available() and hasattr(model, "old_fit"):
        logger.info("Using legacy sentence-transformers training path on MPS to avoid unsupported pin_memory warnings.")
        model.old_fit(**kwargs)
        return
    model.fit(**kwargs)


def _face_text_records(db) -> list[FaceTextRecord]:
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
    return normalize_oracle_text(
        text=face.oracle_text,
        card_name=face.name,
        type_line=face.type_line,
    )


def build_training_dataset_state(db) -> TrainingDatasetState:
    logger.info("Loading face text for semantic training.")
    face_records = _face_text_records(db)
    face_texts = {face.id: _normalize_face_record(face) for face in face_records}
    card_face_map: dict[str, list[int]] = defaultdict(list)
    for face in face_records:
        card_face_map[face.card_id].append(face.id)

    self_pair_ids = [(face_id, face_id) for face_id, text in face_texts.items() if text.strip()]

    tag_to_face_ids: dict[str, list[int]] = defaultdict(list)
    try:
        from ..core.models import CardTagging, Tag
    except Exception as exc:  # pragma: no cover - current branch safety
        raise RuntimeError("Tag models are unavailable in the current codebase state.") from exc

    logger.info("Building tag-derived positive pairs.")
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
        if len(fids) < MAX_TAG_PAIR_GROUP_SIZE:
            continue
        random.shuffle(fids)
        for a, b in list(zip(fids[::2], fids[1::2]))[:MAX_TAG_PAIRS_PER_TAG]:
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
        "pair_ids": [[left_face_id, right_face_id] for left_face_id, right_face_id in dataset_state.pair_ids],
        "simcse_examples": dataset_state.simcse_examples,
        "tag_pair_examples": dataset_state.tag_pair_examples,
    }
    output_path.write_text(json.dumps(payload), encoding="utf-8")


def load_training_dataset(input_path: Path) -> TrainingDatasetState:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    face_texts = {int(record["id"]): str(record["text"]) for record in payload["face_texts"]}
    pair_ids = [(int(left_face_id), int(right_face_id)) for left_face_id, right_face_id in payload["pair_ids"]]
    return TrainingDatasetState(
        face_texts=face_texts,
        pair_ids=pair_ids,
        simcse_examples=int(payload["simcse_examples"]),
        tag_pair_examples=int(payload["tag_pair_examples"]),
    )


def export_training_dataset_from_db(output_path: Path) -> int:
    logger.info("Exporting semantic training dataset to %s", output_path)
    db = SessionLocal()
    try:
        dataset_state = build_training_dataset_state(db)
    finally:
        db.close()

    export_training_dataset(dataset_state, output_path)
    logger.info(
        "Exported semantic training dataset. normalized_faces=%d total_examples=%d simcse_examples=%d tag_pair_examples=%d",
        len(dataset_state.face_texts),
        len(dataset_state.pair_ids),
        dataset_state.simcse_examples,
        dataset_state.tag_pair_examples,
    )
    return 0


def prepare_training_dataset_file(output_path: Path) -> Path:
    logger.info("Preparing semantic training dataset file at %s", output_path)
    db = SessionLocal()
    try:
        dataset_state = build_training_dataset_state(db)
    finally:
        db.close()

    export_training_dataset(dataset_state, output_path)
    logger.info(
        "Prepared semantic training dataset file. normalized_faces=%d total_examples=%d simcse_examples=%d tag_pair_examples=%d",
        len(dataset_state.face_texts),
        len(dataset_state.pair_ids),
        dataset_state.simcse_examples,
        dataset_state.tag_pair_examples,
    )

    del dataset_state
    gc.collect()
    logger.info("Released in-memory training dataset state after export.")
    return output_path


def train_dataset_state(
    dataset_state: TrainingDatasetState,
    *,
    output_path: Path,
) -> int:
    SentenceTransformer, InputExample, losses = _load_sentence_transformers()
    _ensure_training_dependencies()
    cache_dir = huggingface_cache_dir()
    checkpoint_path = output_path.parent / CHECKPOINT_DIR_NAME

    logger.info("Starting semantic model training")
    logger.info("  base_model=%s", BASE_MODEL_NAME)
    logger.info("  output_path=%s", output_path)
    logger.info("  checkpoint_path=%s", checkpoint_path)
    logger.info("  chace_dir=%s", cache_dir)

    if not dataset_state.pair_ids:
        logger.error("No semantic training examples found; nothing to train.")
        return 1

    logger.info(
        "Built training dataset. normalized_faces=%d total_examples=%d simcse_examples=%d tag_pair_examples=%d",
        len(dataset_state.face_texts),
        len(dataset_state.pair_ids),
        dataset_state.simcse_examples,
        dataset_state.tag_pair_examples,
    )

    logger.info("Loading base sentence-transformers model: %s", BASE_MODEL_NAME)
    model = SentenceTransformer(BASE_MODEL_NAME)
    logger.info("Base model loaded successfully.")

    try:
        torch_utils_data = import_module("torch.utils.data")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError("torch is required for semantic training.") from exc
    DataLoader = getattr(torch_utils_data, "DataLoader")

    training_dataset = LazyInputExampleDataset(dataset_state.pair_ids, dataset_state.face_texts, InputExample)
    dataloader = DataLoader(training_dataset, shuffle=False, batch_size=BATCH_SIZE)
    loss = losses.MultipleNegativesRankingLoss(model)

    warmup_steps = max(MIN_WARMUP_STEPS, len(training_dataset) // WARMUP_DIVISOR)
    logger.info(
        "Training semantic model. examples=%d epochs=%d batch_size=%d warmup_steps=%d checkpoint_path=%s",
        len(training_dataset),
        EPOCHS,
        BATCH_SIZE,
        warmup_steps,
        checkpoint_path,
    )

    checkpoint_path.mkdir(parents=True, exist_ok=True)
    logger.info("Starting semantic model fit.")
    _fit_model(
        model,
        train_objectives=[(dataloader, loss)],
        epochs=EPOCHS,
        warmup_steps=warmup_steps,
        show_progress_bar=True,
        checkpoint_path=str(checkpoint_path),
    )

    logger.info("Training complete. Saving semantic model to %s", output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    model.save(str(output_path))
    logger.info("Semantic model saved to %s", output_path)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ot_backend.embed.train")
    parser.add_argument(
        "--dataset-path",
        type=Path,
        help="Train from a previously exported dataset instead of querying the database.",
    )
    parser.add_argument(
        "--export-training-data",
        type=Path,
        help="Export normalized face texts and pair ids to a JSON file, then exit.",
    )
    parser.add_argument(
        "--output-path",
        type=str,
        help="Override the trained model output path for this run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parsed_argv = argv if argv is not None else []
    args = _build_parser().parse_args(parsed_argv)

    if args.export_training_data is not None:
        return export_training_dataset_from_db(args.export_training_data)

    output_path = _training_output_path(args.output_path)
    if args.dataset_path is not None:
        dataset_state = load_training_dataset(args.dataset_path)
        logger.info("Loaded exported semantic training dataset from %s", args.dataset_path)
        return train_dataset_state(dataset_state, output_path=output_path)

    dataset_path = output_path.parent / TRAINING_DATASET_FILE_NAME
    _ = prepare_training_dataset_file(dataset_path)
    dataset_state = load_training_dataset(dataset_path)
    logger.info("Loaded exported semantic training dataset from %s", dataset_path)
    return train_dataset_state(dataset_state, output_path=output_path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
