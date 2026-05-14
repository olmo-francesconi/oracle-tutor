"""Train a semantic model bundle and register it.

Usage (from backend/):
    uv run python -m scripts.train_model \\
        --dataset-id <uuid> --slug my-model --base-model mini-lm-l6-v2
    uv run python -m scripts.train_model \\
        --dataset-id <uuid> --slug my-model --base-model mini-lm-l6-v2 \\
        --skip-fine-tune
    uv run python -m scripts.train_model \\
        --dataset-id <uuid> --slug my-model --base-model mini-lm-l6-v2 --prod
"""
from __future__ import annotations

import argparse
import logging
import sys

from ._common import add_prod_flag, get_session, load_env, setup_logging

logger = logging.getLogger("ot_backend.semantic.scripts.train_model")

_DEFAULT_EPOCHS = 3
_DEFAULT_BATCH_SIZE = 32


def _build_parser() -> argparse.ArgumentParser:
    from ot_backend.semantic.train_options import (
        DEFAULT_TRAIN_QUANTIZATION,
        TRAIN_QUANTIZATION_OPTIONS,
    )

    parser = argparse.ArgumentParser(prog="python -m scripts.train_model")
    parser.add_argument("--dataset-id", required=True, help="UUID of the source semantic dataset.")
    parser.add_argument("--slug", required=True, help="Model slug (unique identifier).")
    parser.add_argument("--base-model", required=True, help="Base model key (e.g. mini-lm-l6-v2).")
    parser.add_argument("--epochs", type=int, default=_DEFAULT_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=_DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--quantization",
        choices=TRAIN_QUANTIZATION_OPTIONS,
        default=DEFAULT_TRAIN_QUANTIZATION,
        help="Post-export ONNX weight quantization (applied to runtime model). Default: none.",
    )
    parser.add_argument(
        "--skip-fine-tune",
        action="store_true",
        default=False,
        help="Export the base model as-is without fine-tuning (runs locally via modal_train.train.local()).",
    )
    add_prod_flag(parser)
    return parser


def _run_local_base_model_export(
    *,
    dataset_bytes: bytes,
    eval_queries_bytes: bytes,
    base_model: str,
    epochs: int,
    batch_size: int,
    augmentation_mode: str,
    quantization: str,
) -> bytes:
    from importlib import import_module

    try:
        modal_train = import_module("ot_backend.semantic.modal_train")
    except Exception as exc:
        raise RuntimeError("Packaged Modal training module could not be imported.") from exc

    train_fn = getattr(modal_train, "train", None)
    if train_fn is None or not hasattr(train_fn, "local"):
        raise RuntimeError("Packaged training module does not expose a callable train.local().")
    logger.info("Running local base model export (skip_fine_tune=True, quantization=%s).", quantization)
    return train_fn.local(
        dataset_bytes,
        eval_queries_bytes,
        base_model,
        epochs,
        batch_size,
        augmentation_mode,
        True,
        quantization,
    )


def _run_modal_training(
    *,
    dataset_bytes: bytes,
    eval_queries_bytes: bytes,
    base_model: str,
    epochs: int,
    batch_size: int,
    augmentation_mode: str,
    quantization: str,
) -> bytes:
    from importlib import import_module

    from ot_backend.core.config import modal_client_configured, modal_environment_name

    if not modal_client_configured():
        raise RuntimeError(
            "Modal client credentials are not configured. Expected MODAL_TOKEN_ID and MODAL_TOKEN_SECRET."
        )
    try:
        modal_train = import_module("ot_backend.semantic.modal_train")
    except Exception as exc:
        raise RuntimeError("Packaged Modal training module could not be imported.") from exc

    train_fn = getattr(modal_train, "train", None)
    if train_fn is None or not hasattr(train_fn, "remote"):
        raise RuntimeError("Packaged Modal training module does not expose a callable train.remote().")
    app = getattr(modal_train, "app", None)
    if app is None or not hasattr(app, "run"):
        raise RuntimeError("Packaged Modal training module does not expose a Modal App.")

    logger.info(
        "Running Modal training. base_model=%s epochs=%d batch_size=%d quantization=%s",
        base_model,
        epochs,
        batch_size,
        quantization,
    )
    with app.run(environment_name=modal_environment_name()):
        return train_fn.remote(
            dataset_bytes,
            eval_queries_bytes,
            base_model,
            epochs,
            batch_size,
            augmentation_mode,
            False,
            quantization,
        )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    load_env(prod=args.prod)
    setup_logging()

    from ot_backend.semantic.base_model_catalog import get_semantic_base_model
    from ot_backend.semantic.bundle_registration import register_model_bundle_bytes, semantic_model_artifact_keys
    from ot_backend.semantic.dataset_registry import get_semantic_dataset, get_semantic_dataset_bytes
    from ot_backend.semantic.eval_service import default_eval_queries_bytes
    from ot_backend.semantic.train_options import validate_train_quantization

    quantization = validate_train_quantization(args.quantization)

    base_model_spec = get_semantic_base_model(args.base_model)

    SessionLocal = get_session()
    with SessionLocal() as db:
        dataset = get_semantic_dataset(db, args.dataset_id)
        if dataset is None:
            logger.error("Dataset not found. id=%s", args.dataset_id)
            return 1
        augmentation_mode = dataset.augmentation_mode
        dataset_slug = dataset.slug
        dataset_bytes = get_semantic_dataset_bytes(db, args.dataset_id)

    eval_queries_bytes = default_eval_queries_bytes()

    if args.skip_fine_tune:
        bundle_bytes = _run_local_base_model_export(
            dataset_bytes=dataset_bytes,
            eval_queries_bytes=eval_queries_bytes,
            base_model=base_model_spec.base_model,
            epochs=args.epochs,
            batch_size=args.batch_size,
            augmentation_mode=augmentation_mode,
            quantization=quantization,
        )
    else:
        bundle_bytes = _run_modal_training(
            dataset_bytes=dataset_bytes,
            eval_queries_bytes=eval_queries_bytes,
            base_model=base_model_spec.base_model,
            epochs=args.epochs,
            batch_size=args.batch_size,
            augmentation_mode=augmentation_mode,
            quantization=quantization,
        )

    with SessionLocal() as db:
        model = register_model_bundle_bytes(
            db,
            slug=args.slug,
            base_model=base_model_spec.base_model,
            embedding_dim=base_model_spec.embedding_dim,
            artifact_bundle_bytes=bundle_bytes,
            dataset_id=args.dataset_id,
            dataset_bytes=dataset_bytes,
            source_semantic_data_version=None,
            augmentation_mode=augmentation_mode,
            config_json={"base_model_key": args.base_model, "dataset_slug": dataset_slug},
            metrics_json=None,
        )
        model_id = model.id
        artifact_keys = semantic_model_artifact_keys(db, model_id)

    logger.info("Model registered. id=%s slug=%s", model_id, args.slug)
    print(f"model_id={model_id}")
    for kind, key in artifact_keys.items():
        print(f"artifact:{kind}={key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
