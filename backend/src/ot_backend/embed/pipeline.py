from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..core.config import DEFAULT_SEMANTIC_BASE_MODEL, DEFAULT_SEMANTIC_RUNS_DIR
from ..core.database import SessionLocal
from ..core.logging_config import setup_loggers
from .dataset_service import (
    TRAINING_DATASET_FILE_NAME,
    TrainingDatasetState,
    build_training_dataset_state,  # noqa: F401
    export_training_dataset,  # noqa: F401
    export_training_dataset_bytes,
    load_training_dataset,
    load_training_dataset_bytes,
    load_training_dataset_payload_bytes,
    prepare_and_save_dataset,
)
from .eval_service import build_eval_json_bytes, default_eval_queries_bytes, load_eval_queries_payload
from .model_registry import (
    begin_semantic_model_promotion,
    bundle_model_directory,
    run_semantic_model_promotion,
    validate_model_bundle,
)
from .registration import register_model_bundle_bytes
from .semantic_state import record_exported_dataset_version
from .training_service import (
    CHECKPOINT_DIR_NAME,
    EMBED_WRITE_BATCH_SIZE,
    LazyInputExampleDataset,  # noqa: F401
    _load_sentence_transformer_class,
    compute_embeddings,
    export_onnx_model,
    train_sentence_transformer,
)

logger = logging.getLogger("ot_backend.embed.pipeline")

_DEFAULT_BASE_MODEL = os.environ.get("SEMANTIC_BASE_MODEL", DEFAULT_SEMANTIC_BASE_MODEL)
_DEFAULT_RUNS_DIR = Path(os.environ.get("SEMANTIC_RUNS_DIR", str(DEFAULT_SEMANTIC_RUNS_DIR)))
_RUN_DATASET_RELATIVE_PATH = Path("training") / TRAINING_DATASET_FILE_NAME
_RUN_EMBEDDINGS_RELATIVE_PATH = Path("embeddings") / "embeddings.npz"
_RUN_PYTORCH_RELATIVE_PATH = Path("models") / "pytorch"
_RUN_ONNX_RELATIVE_PATH = Path("models") / "onnx"
_RUN_EVAL_RELATIVE_PATH = Path("eval") / "eval.json"
_EVAL_TOP_K = 5
_EVAL_TEXT_PREVIEW = 90


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
        payload = asdict(self)
        payload["dataset_path"] = str(payload["dataset_path"]) if payload["dataset_path"] else None
        payload["runs_dir"] = str(payload["runs_dir"])
        return json.dumps(payload, indent=2)

    @classmethod
    def from_json_file(cls, path: Path) -> PipelineConfig:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("dataset_path"):
            payload["dataset_path"] = Path(payload["dataset_path"])
        if payload.get("runs_dir"):
            payload["runs_dir"] = Path(payload["runs_dir"])
        return cls(**payload)


def _bundle_dataset_path(run_dir: Path) -> Path:
    return run_dir / _RUN_DATASET_RELATIVE_PATH


def _bundle_embeddings_path(run_dir: Path) -> Path:
    return run_dir / _RUN_EMBEDDINGS_RELATIVE_PATH


def _bundle_eval_path(run_dir: Path) -> Path:
    return run_dir / _RUN_EVAL_RELATIVE_PATH


def _bundle_pytorch_path(run_dir: Path) -> Path:
    return run_dir / _RUN_PYTORCH_RELATIVE_PATH


def _bundle_onnx_path(run_dir: Path) -> Path:
    return run_dir / _RUN_ONNX_RELATIVE_PATH


def _dataset_metadata_from_bytes(dataset_bytes: bytes) -> dict[str, object]:
    payload = load_training_dataset_payload_bytes(dataset_bytes)
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    return {str(key): value for key, value in metadata.items()}


def _prepare_and_save_dataset(output_path: Path, config: PipelineConfig) -> None:
    prepare_and_save_dataset(
        output_path,
        max_tag_pairs_per_tag=config.max_tag_pairs_per_tag,
        max_tag_pair_group_size=config.max_tag_pair_group_size,
        max_tag_desc_pairs_per_tag=config.max_tag_desc_pairs_per_tag,
    )


def _train(config: PipelineConfig, dataset_state: TrainingDatasetState, run_dir: Path) -> Any:
    return train_sentence_transformer(
        base_model=config.base_model,
        dataset_state=dataset_state,
        epochs=config.epochs,
        batch_size=config.batch_size,
        warmup_divisor=config.warmup_divisor,
        min_warmup_steps=config.min_warmup_steps,
        checkpoint_dir=run_dir / CHECKPOINT_DIR_NAME,
    )


def _compute_embeddings(model: Any, batch_size: int = 256, output_path: Path | None = None) -> int:
    return compute_embeddings(model, batch_size=batch_size, output_path=output_path)


def _make_run_id(run_name: str | None = None) -> str:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    if run_name:
        return f"{timestamp}-{run_name}"
    return timestamp


def _write_eval_artifact(model: Any, *, dataset_state: TrainingDatasetState, embeddings_path: Path, output_path: Path) -> dict[str, object]:
    data = np.load(embeddings_path, allow_pickle=False)
    oracle_ids: list[str] = data["oracle_ids"].tolist()
    face_ixs: list[int] = data["face_ixs"].tolist()
    embeddings: np.ndarray = np.asarray(data["embeddings"], dtype=np.float32)
    eval_bytes, eval_summary = build_eval_json_bytes(
        model,
        face_texts=dataset_state.face_texts,
        face_names=dataset_state.face_names,
        oracle_ids=oracle_ids,
        face_ixs=face_ixs,
        embeddings=embeddings,
        eval_queries_bytes=default_eval_queries_bytes(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(eval_bytes)
    return eval_summary


def _write_run_manifest(
    run_dir: Path,
    *,
    dataset_metadata: dict[str, object],
    has_embeddings: bool,
    has_eval_json: bool,
) -> None:
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "bundle": {
                    "has_onnx_model": True,
                    "has_pytorch_model": True,
                    "has_precomputed_embeddings": has_embeddings,
                    "has_training_dataset": True,
                    "has_eval_json": has_eval_json,
                },
                "source_semantic_data_version": dataset_metadata.get("semantic_data_version"),
                "dataset_metadata": dataset_metadata,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_run_config(run_dir: Path, *, config: PipelineConfig, dataset_metadata: dict[str, object]) -> None:
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "base_model": config.base_model,
                "epochs": config.epochs,
                "batch_size": config.batch_size,
                "embed_batch_size": config.embed_batch_size,
                "skip_fine_tune": config.skip_fine_tune,
                "skip_embeddings": config.skip_embeddings,
                "dataset_metadata": dataset_metadata,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_pipeline(config: PipelineConfig, run_dir: Path) -> int:
    t0 = time.monotonic()
    metrics: dict[str, Any] = {"run_id": run_dir.name, "base_model": config.base_model}

    dataset_output_path = _bundle_dataset_path(run_dir)
    if config.dataset_path is not None:
        dataset_output_path.parent.mkdir(parents=True, exist_ok=True)
        dataset_output_path.write_bytes(config.dataset_path.read_bytes())
        logger.info("Copied pre-exported dataset into run artifact dir: %s", dataset_output_path)
    else:
        _prepare_and_save_dataset(dataset_output_path, config)

    dataset_bytes = dataset_output_path.read_bytes()
    dataset_state = load_training_dataset_bytes(dataset_bytes)
    dataset_metadata = _dataset_metadata_from_bytes(dataset_bytes)
    _write_run_config(run_dir, config=config, dataset_metadata=dataset_metadata)

    metrics["dataset"] = {
        "normalized_faces": len(dataset_state.face_texts),
        "total_examples": len(dataset_state.pair_ids) + len(dataset_state.direct_text_pairs),
        "simcse_examples": dataset_state.simcse_examples,
        "tag_pair_examples": dataset_state.tag_pair_examples,
        "tag_desc_pair_examples": dataset_state.tag_desc_pair_examples,
        "template_query_examples": dataset_state.template_query_examples,
    }

    if config.skip_fine_tune:
        logger.info("Skipping fine-tuning (--no-fine-tune). Using base model: %s", config.base_model)
        SentenceTransformer = _load_sentence_transformer_class()
        model = SentenceTransformer(config.base_model)
    else:
        t_train = time.monotonic()
        model = _train(config, dataset_state, run_dir)
        metrics["training_duration_seconds"] = round(time.monotonic() - t_train, 1)

    embeddings_path = _bundle_embeddings_path(run_dir)
    eval_output_path = _bundle_eval_path(run_dir)
    if not config.skip_embeddings:
        metrics["embedding_count"] = _compute_embeddings(
            model,
            batch_size=config.embed_batch_size,
            output_path=embeddings_path,
        )
        if embeddings_path.exists():
            metrics["eval_summary"] = _write_eval_artifact(
                model,
                dataset_state=dataset_state,
                embeddings_path=embeddings_path,
                output_path=eval_output_path,
            )

    pytorch_path = _bundle_pytorch_path(run_dir)
    pytorch_path.mkdir(parents=True, exist_ok=True)
    model.save(str(pytorch_path))
    logger.info("PyTorch model saved to %s", pytorch_path)

    export_onnx_model(str(pytorch_path), _bundle_onnx_path(run_dir))
    _write_run_manifest(
        run_dir,
        dataset_metadata=dataset_metadata,
        has_embeddings=embeddings_path.exists(),
        has_eval_json=eval_output_path.exists(),
    )

    metrics["total_duration_seconds"] = round(time.monotonic() - t0, 1)
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    logger.info("Pipeline complete. run_id=%s duration=%.1fs", run_dir.name, metrics["total_duration_seconds"])
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ot_backend.embed.pipeline")
    parser.add_argument("--run-name", help="Label appended to the run ID (e.g. 'larger-batch').")
    parser.add_argument("--epochs", type=int, help="Training epochs (default: 5).")
    parser.add_argument("--batch-size", type=int, help="Training batch size (default: 8).")
    parser.add_argument("--base-model", help="HuggingFace model ID or local path.")
    parser.add_argument(
        "--max-tag-desc-pairs-per-tag",
        type=int,
        help="Max tag-description anchor pairs per tag (default: 20).",
    )
    parser.add_argument("--no-fine-tune", action="store_true", help="Skip training; use base model for embeddings and ONNX export.")
    parser.add_argument("--no-embeddings", action="store_true", help="Skip embedding computation.")
    parser.add_argument("--embed-batch-size", type=int, help="Batch size for embedding computation (default: 256).")
    parser.add_argument("--dataset-path", type=Path, help="Use a pre-exported training dataset JSON for the local pipeline run.")
    parser.add_argument("--export-dataset", type=Path, help="Export training dataset to JSON and exit.")
    parser.add_argument("--register-model", type=Path, help="Register a zipped model bundle or model directory in the DB registry.")
    parser.add_argument("--model-slug", help="Slug or label for --register-model.")
    parser.add_argument("--model-config-json", type=Path, help="Optional JSON object merged into the registered model config.")
    parser.add_argument("--model-metrics-json", type=Path, help="Optional JSON object merged into the registered model metrics.")
    parser.add_argument("--source-semantic-data-version", type=int, help="Explicit source semantic data version for model registration.")
    parser.add_argument(
        "--augmentation-mode",
        default="none",
        help="Training dataset augmentation mode metadata stored with registered models (default: none).",
    )
    parser.add_argument("--config", type=Path, help="Load PipelineConfig defaults from a JSON file.")
    parser.add_argument("--runs-dir", type=Path, help="Override the runs root directory.")
    parser.add_argument("--promote-model", type=str, help="Promote a registered semantic model by ID.")
    parser.add_argument(
        "--reembed-only",
        action="store_true",
        help="Recompute DB embeddings from an explicit model source without training or writing run artifacts.",
    )
    parser.add_argument(
        "--eval",
        action="store_true",
        help="Run eval queries against an explicit local run artifact directory.",
    )
    parser.add_argument(
        "--eval-run-dir",
        type=Path,
        help="Run artifact directory containing models/, embeddings/, training/, and eval/ outputs.",
    )
    parser.add_argument(
        "--eval-queries",
        type=Path,
        help="Optional eval queries JSON. Defaults to the packaged eval query set.",
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


def _load_optional_json_file(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return {str(key): value for key, value in payload.items()}


def _model_bundle_bytes(bundle_path: Path) -> bytes:
    if bundle_path.is_dir():
        return bundle_model_directory(bundle_path)
    bundle_bytes = bundle_path.read_bytes()
    validate_model_bundle(bundle_bytes)
    return bundle_bytes


def register_model_bundle(
    bundle_path: Path,
    *,
    slug: str,
    base_model: str,
    source_semantic_data_version: int | None,
    augmentation_mode: str,
    config_json_path: Path | None,
    metrics_json_path: Path | None,
) -> str:
    bundle_bytes = _model_bundle_bytes(bundle_path)
    extra_config_json = _load_optional_json_file(config_json_path)
    extra_metrics_json = _load_optional_json_file(metrics_json_path)

    with SessionLocal() as db:
        model = register_model_bundle_bytes(
            db,
            slug=slug,
            base_model=base_model,
            embedding_dim=384,
            artifact_bundle_bytes=bundle_bytes,
            source_semantic_data_version=source_semantic_data_version,
            augmentation_mode=augmentation_mode,
            config_json=extra_config_json,
            metrics_json=extra_metrics_json,
        )
    logger.info("Registered semantic model. id=%s slug=%s", model.id, model.slug)
    return model.id


def _register_model(
    bundle_path: Path,
    *,
    slug: str,
    base_model: str,
    source_semantic_data_version: int | None,
    augmentation_mode: str,
    config_json_path: Path | None,
    metrics_json_path: Path | None,
) -> int:
    _ = register_model_bundle(
        bundle_path,
        slug=slug,
        base_model=base_model,
        source_semantic_data_version=source_semantic_data_version,
        augmentation_mode=augmentation_mode,
        config_json_path=config_json_path,
        metrics_json_path=metrics_json_path,
    )
    return 0


def _run_eval(*, run_dir: Path, model_source: str | None, eval_path: Path | None) -> int:
    embeddings_path = _bundle_embeddings_path(run_dir)
    dataset_path = _bundle_dataset_path(run_dir)

    if not embeddings_path.exists():
        raise FileNotFoundError(f"Embeddings not found at {embeddings_path}.")
    if not dataset_path.exists():
        raise FileNotFoundError(f"Training dataset not found at {dataset_path}.")
    if eval_path is not None and not eval_path.exists():
        raise FileNotFoundError(f"Eval queries file not found: {eval_path}")

    resolved_model = model_source or str(_bundle_pytorch_path(run_dir))
    logger.info("Loading model from %s", resolved_model)
    SentenceTransformer = _load_sentence_transformer_class()
    model = SentenceTransformer(resolved_model)

    logger.info("Loading embeddings from %s", embeddings_path)
    data = np.load(embeddings_path, allow_pickle=False)
    oracle_ids: list[str] = data["oracle_ids"].tolist()
    face_ixs: list[int] = data["face_ixs"].tolist()
    embeddings: np.ndarray = np.asarray(data["embeddings"], dtype=np.float32)

    logger.info("Loading face texts from %s", dataset_path)
    dataset_state = load_training_dataset(dataset_path)
    face_texts = dataset_state.face_texts

    eval_queries_payload = load_eval_queries_payload(eval_path.read_bytes() if eval_path is not None else None)
    queries = eval_queries_payload["queries"]
    logger.info("Running eval. queries=%d top_k=%d", len(queries), _EVAL_TOP_K)

    for item in queries:
        query: str = item["query"]
        expected: list[str] = item.get("expected_cards", [])
        notes: str = item.get("notes", "")

        query_emb = model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
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
    dataset_bytes = export_training_dataset_bytes()
    dataset_state = load_training_dataset_bytes(dataset_bytes)
    dataset_metadata = _dataset_metadata_from_bytes(dataset_bytes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(dataset_bytes)

    with SessionLocal() as db:
        raw_sdv = dataset_metadata.get("semantic_data_version")
        semantic_data_version = int(raw_sdv) if isinstance(raw_sdv, (int, str)) else 0
        if semantic_data_version > 0:
            record_exported_dataset_version(db, semantic_data_version)

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

    if args.register_model is not None:
        if not args.model_slug:
            raise ValueError("--model-slug is required with --register-model.")
        if args.dataset_path is not None:
            raise ValueError("--dataset-path is only valid for local pipeline runs, not --register-model.")

        config = PipelineConfig.from_json_file(args.config) if args.config else PipelineConfig()
        _apply_cli_overrides(config, args)

        base_model = args.base_model or config.base_model
        return _register_model(
            args.register_model,
            slug=args.model_slug,
            base_model=base_model,
            source_semantic_data_version=args.source_semantic_data_version,
            augmentation_mode=args.augmentation_mode,
            config_json_path=args.model_config_json,
            metrics_json_path=args.model_metrics_json,
        )

    if args.promote_model is not None:
        config = PipelineConfig.from_json_file(args.config) if args.config else PipelineConfig()
        _apply_cli_overrides(config, args)
        model = begin_semantic_model_promotion(args.promote_model)
        logger.info("Starting semantic model promotion. id=%s slug=%s", model.id, model.slug)
        succeeded = run_semantic_model_promotion(args.promote_model, embed_batch_size=config.embed_batch_size)
        if not succeeded:
            logger.error("Semantic model promotion failed. id=%s", args.promote_model)
            return 1
        logger.info("Semantic model promotion finished. id=%s", args.promote_model)
        return 0

    config = PipelineConfig.from_json_file(args.config) if args.config else PipelineConfig()
    _apply_cli_overrides(config, args)

    if args.eval:
        if args.eval_run_dir is None:
            raise ValueError("--eval-run-dir is required with --eval.")
        return _run_eval(
            run_dir=args.eval_run_dir,
            model_source=config.base_model if args.base_model else None,
            eval_path=args.eval_queries,
        )

    if args.reembed_only:
        return _reembed(config.base_model, embed_batch_size=config.embed_batch_size)

    run_id = _make_run_id(config.run_name)
    run_dir = config.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting pipeline. run_id=%s run_dir=%s", run_id, run_dir)
    return run_pipeline(config, run_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
