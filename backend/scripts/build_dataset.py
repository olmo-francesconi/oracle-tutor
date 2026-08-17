"""Build a semantic training dataset and upload it to S3.

Usage (from backend/):
    uv run python -m scripts.build_dataset --name my-dataset
    uv run python -m scripts.build_dataset --name my-dataset --augmentation tag_pairs,template_queries
    uv run python -m scripts.build_dataset --name my-dataset --prod
"""
from __future__ import annotations

import argparse
import logging
import sys

from ._common import add_prod_flag, get_session, load_env, setup_logging

logger = logging.getLogger("ot_backend.semantic.scripts.build_dataset")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.build_dataset")
    parser.add_argument("--name", required=True, help="Dataset slug (unique identifier).")
    parser.add_argument(
        "--augmentation",
        default=None,
        help=(
            "Comma-separated augmentation keys. "
            "Defaults to all non-LLM augmentations (tag_pairs,tag_descriptions,template_queries). "
            "Use 'none' for no augmentation. Add 'llm_queries' to trigger Modal LLM build."
        ),
    )
    add_prod_flag(parser)
    return parser


def _run_modal_dataset_build(*, training_payload_bytes: bytes, augmentation_mode: str) -> bytes:
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

    build_fn = getattr(modal_train, "build_dataset", None)
    if build_fn is None or not hasattr(build_fn, "remote"):
        raise RuntimeError("Modal training module does not expose a callable build_dataset.remote().")
    app = getattr(modal_train, "app", None)
    if app is None or not hasattr(app, "run"):
        raise RuntimeError("Modal training module does not expose a Modal App.")

    from ot_backend.core.config import (
        semantic_llm_max_faces,
        semantic_llm_max_queries_per_face,
        semantic_llm_max_tokens,
        semantic_llm_min_template_coverage,
        semantic_llm_model_name,
        semantic_llm_temperature,
    )

    llm_config = {
        "model_name": semantic_llm_model_name(),
        "max_queries_per_face": semantic_llm_max_queries_per_face(),
        "max_faces": semantic_llm_max_faces(),
        "min_template_coverage": semantic_llm_min_template_coverage(),
        "temperature": semantic_llm_temperature(),
        "max_tokens": semantic_llm_max_tokens(),
    }
    with app.run(environment_name=modal_environment_name()):
        return build_fn.remote(training_payload_bytes, augmentation_mode, llm_config)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    load_env(prod=args.prod)
    setup_logging()

    from ot_backend.semantic.dataset_registry import (
        create_semantic_dataset,
        semantic_dataset_artifact_keys,
        semantic_dataset_summary_metrics,
    )
    from ot_backend.semantic.dataset_service import (
        export_training_build_payload_bytes,
        export_training_dataset_bytes,
    )
    from ot_backend.semantic.train_options import (
        DEFAULT_TRAIN_AUGMENTATION_MODE,
        TRAIN_AUGMENTATION_LLM_QUERIES,
        parse_train_augmentation_mode,
    )

    augmentation_mode = args.augmentation if args.augmentation is not None else DEFAULT_TRAIN_AUGMENTATION_MODE
    selected_augmentations = set(parse_train_augmentation_mode(augmentation_mode))

    logger.info("Building dataset. slug=%s augmentation=%s", args.name, augmentation_mode)

    if TRAIN_AUGMENTATION_LLM_QUERIES in selected_augmentations:
        logger.info("LLM augmentation selected — running Modal dataset build.")
        training_payload_bytes = export_training_build_payload_bytes(augmentation_mode=augmentation_mode)
        dataset_bytes = _run_modal_dataset_build(
            training_payload_bytes=training_payload_bytes,
            augmentation_mode=augmentation_mode,
        )
    else:
        dataset_bytes = export_training_dataset_bytes(augmentation_mode=augmentation_mode)

    SessionLocal = get_session()
    with SessionLocal() as db:
        dataset = create_semantic_dataset(
            db,
            slug=args.name,
            augmentation_mode=augmentation_mode,
            dataset_bytes=dataset_bytes,
            metrics_json=semantic_dataset_summary_metrics(dataset_bytes),
        )
        dataset_id = dataset.id
        artifact_keys = semantic_dataset_artifact_keys(db, dataset_id)

    logger.info("Dataset created. id=%s slug=%s", dataset_id, args.name)
    print(f"dataset_id={dataset_id}")
    for kind, key in artifact_keys.items():
        print(f"artifact:{kind}={key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
