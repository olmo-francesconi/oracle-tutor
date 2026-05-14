"""Backfill v2 manifests for models/datasets already in S3.

When the manifest schema changed to embed every field needed to rehydrate a
SemanticModel / SemanticDataset row, existing S3 objects kept their older
manifests. This module walks S3, finds incomplete manifests, downloads the
heavy artifact once (bundle.zip or training-dataset.json), and re-uploads a
fresh v2 manifest. Idempotent: v2 manifests are skipped.
"""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass, field

from ..core.config import artifact_bucket_client, artifact_bucket_name
from .artifacts import (
    SEMANTIC_MANIFEST_VERSION,
    build_semantic_dataset_manifest,
    build_semantic_model_manifest,
    download_artifact_bytes,
    upload_artifact_bytes,
)
from .bundle_registration import (
    load_bundle_embedding_dim,
    load_bundle_sidecar_json,
    load_training_dataset_metadata_from_bytes,
)
from .dataset_registry import semantic_dataset_summary_metrics

logger = logging.getLogger("ot_backend.semantic.manifest_backfill")

_PREFIX = "semantic-registry"
_MODELS_PREFIX = f"{_PREFIX}/models/"
_DATASETS_PREFIX = f"{_PREFIX}/datasets/"


@dataclass
class BackfillReport:
    models_scanned: int = 0
    models_upgraded: int = 0
    models_skipped: int = 0
    models_failed: list[tuple[str, str]] = field(default_factory=list)
    datasets_scanned: int = 0
    datasets_upgraded: int = 0
    datasets_skipped: int = 0
    datasets_failed: list[tuple[str, str]] = field(default_factory=list)


def _list_kind(client, bucket: str, prefix: str) -> dict[str, dict[str, str]]:
    """Return {uuid: {filename: object_key}} for one of the registry prefixes."""
    out: dict[str, dict[str, str]] = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parts = key.split("/")
            if len(parts) != 4:
                continue
            _, _, uuid_part, filename = parts
            out.setdefault(uuid_part, {})[filename] = key
    return out


def _manifest_is_current(manifest: dict[str, object], required: set[str]) -> bool:
    version = manifest.get("version")
    if not isinstance(version, int) or version < SEMANTIC_MANIFEST_VERSION:
        return False
    return all(field_name in manifest for field_name in required)


def _read_manifest(object_key: str) -> dict[str, object] | None:
    try:
        raw = download_artifact_bytes(object_key=object_key)
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _backfill_model(model_id: str, files: dict[str, str]) -> tuple[bool, str]:
    """Returns (upgraded, reason). Skip-reason if not upgraded."""
    if "bundle.zip" not in files:
        return False, "no bundle.zip"

    existing = _read_manifest(files["manifest.json"]) if "manifest.json" in files else {}
    if existing is None:
        existing = {}
    if _manifest_is_current(existing, {"base_model", "embedding_dim", "config", "metrics"}):
        return False, "already v2"

    bundle_bytes = download_artifact_bytes(object_key=files["bundle.zip"])
    bundle_config = load_bundle_sidecar_json(bundle_bytes, "config.json") or {}
    bundle_metrics = load_bundle_sidecar_json(bundle_bytes, "metrics.json") or {}

    base_model = str(bundle_config.get("base_model") or existing.get("base_model") or "unknown")

    embedding_dim = (
        _maybe_int(bundle_config.get("embedding_dim"))
        or _maybe_int(bundle_metrics.get("embedding_dim"))
        or _maybe_int(existing.get("embedding_dim"))
        or _safe_npz_dim(bundle_bytes)
        or 384
    )

    dataset_metadata: dict[str, object] = {}
    if "training-dataset.json" in files:
        try:
            ds_bytes = download_artifact_bytes(object_key=files["training-dataset.json"])
            dataset_metadata = load_training_dataset_metadata_from_bytes(ds_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read training-dataset.json for model %s: %s", model_id, exc)

    source_version = _maybe_int(existing.get("source_semantic_data_version")) or _maybe_int(
        dataset_metadata.get("semantic_data_version")
    )

    manifest_bytes = build_semantic_model_manifest(
        bundle_bytes=bundle_bytes,
        base_model=base_model,
        embedding_dim=embedding_dim,
        bundle_config=bundle_config,
        bundle_metrics=bundle_metrics,
        dataset_metadata=dataset_metadata,
        source_semantic_data_version=source_version,
    )

    manifest_key = files.get("manifest.json", f"{_MODELS_PREFIX}{model_id}/manifest.json")
    upload_artifact_bytes(
        object_key=manifest_key,
        content_bytes=manifest_bytes,
        content_type="application/json",
    )
    return True, "upgraded"


def _backfill_dataset(dataset_id: str, files: dict[str, str]) -> tuple[bool, str]:
    if "training-dataset.json" not in files:
        return False, "no training-dataset.json"

    existing = _read_manifest(files["manifest.json"]) if "manifest.json" in files else {}
    if existing is None:
        existing = {}
    if _manifest_is_current(existing, {"augmentation_mode", "dataset_metrics"}):
        return False, "already v2"

    ds_bytes = download_artifact_bytes(object_key=files["training-dataset.json"])
    dataset_metadata = load_training_dataset_metadata_from_bytes(ds_bytes)
    dataset_metrics = semantic_dataset_summary_metrics(ds_bytes)

    augmentation_mode = str(existing.get("augmentation_mode") or dataset_metadata.get("augmentation_mode") or "none")
    source_version = _maybe_int(existing.get("source_semantic_data_version")) or _maybe_int(
        dataset_metadata.get("semantic_data_version")
    )

    manifest_bytes = build_semantic_dataset_manifest(
        dataset_metadata=dataset_metadata,
        augmentation_mode=augmentation_mode,
        source_semantic_data_version=source_version,
        dataset_metrics=dataset_metrics,
    )
    manifest_key = files.get("manifest.json", f"{_DATASETS_PREFIX}{dataset_id}/manifest.json")
    upload_artifact_bytes(
        object_key=manifest_key,
        content_bytes=manifest_bytes,
        content_type="application/json",
    )
    return True, "upgraded"


def _maybe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _safe_npz_dim(bundle_bytes: bytes) -> int | None:
    try:
        return load_bundle_embedding_dim(bundle_bytes)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        return None
    except Exception:  # noqa: BLE001
        return None


def backfill_manifests() -> BackfillReport:
    """Scan the registry bucket and upgrade every incomplete manifest to v2."""
    client = artifact_bucket_client()
    bucket = artifact_bucket_name()
    report = BackfillReport()

    models = _list_kind(client, bucket, _MODELS_PREFIX)
    datasets = _list_kind(client, bucket, _DATASETS_PREFIX)

    for model_id, files in models.items():
        report.models_scanned += 1
        try:
            upgraded, reason = _backfill_model(model_id, files)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Backfill failed for model %s", model_id)
            report.models_failed.append((model_id, str(exc)))
            continue
        if upgraded:
            report.models_upgraded += 1
            logger.info("Upgraded manifest for model %s", model_id)
        else:
            report.models_skipped += 1
            logger.debug("Skipped model %s (%s)", model_id, reason)

    for dataset_id, files in datasets.items():
        report.datasets_scanned += 1
        try:
            upgraded, reason = _backfill_dataset(dataset_id, files)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Backfill failed for dataset %s", dataset_id)
            report.datasets_failed.append((dataset_id, str(exc)))
            continue
        if upgraded:
            report.datasets_upgraded += 1
            logger.info("Upgraded manifest for dataset %s", dataset_id)
        else:
            report.datasets_skipped += 1
            logger.debug("Skipped dataset %s (%s)", dataset_id, reason)

    return report
