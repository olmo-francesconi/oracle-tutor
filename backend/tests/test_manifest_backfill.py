"""Tests for the v2 manifest schema and the S3 backfill that upgrades older manifests."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import numpy as np
import pytest

from ot_backend.semantic.artifacts import (
    SEMANTIC_MANIFEST_VERSION,
    build_semantic_dataset_manifest,
    build_semantic_model_manifest,
)
from ot_backend.semantic import manifest_backfill


# ---------------------------------------------------------------------------
# Manifest builder tests
# ---------------------------------------------------------------------------


def _empty_bundle_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("config.json", "{}")
    return buf.getvalue()


def test_model_manifest_carries_all_rehydration_fields() -> None:
    manifest = json.loads(
        build_semantic_model_manifest(
            bundle_bytes=_empty_bundle_bytes(),
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_dim=384,
            bundle_config={"epochs": 3, "lr": 2e-5},
            bundle_metrics={"loss": 0.05},
            dataset_metadata={"semantic_data_version": 7},
            source_semantic_data_version=7,
        ).decode("utf-8")
    )

    assert manifest["version"] == SEMANTIC_MANIFEST_VERSION
    assert manifest["base_model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert manifest["embedding_dim"] == 384
    assert manifest["config"] == {"epochs": 3, "lr": 2e-5}
    assert manifest["metrics"] == {"loss": 0.05}
    assert manifest["source_semantic_data_version"] == 7
    assert manifest["dataset_metadata"]["semantic_data_version"] == 7
    assert "bundle" in manifest


def test_dataset_manifest_carries_metrics() -> None:
    manifest = json.loads(
        build_semantic_dataset_manifest(
            dataset_metadata={"semantic_data_version": 3},
            augmentation_mode="paraphrase",
            source_semantic_data_version=3,
            dataset_metrics={"face_count": 42, "pair_count": 100},
        ).decode("utf-8")
    )

    assert manifest["version"] == SEMANTIC_MANIFEST_VERSION
    assert manifest["augmentation_mode"] == "paraphrase"
    assert manifest["source_semantic_data_version"] == 3
    assert manifest["dataset_metrics"] == {"face_count": 42, "pair_count": 100}


# ---------------------------------------------------------------------------
# Backfill tests — fake S3 in-memory
# ---------------------------------------------------------------------------


class _FakeS3:
    """Minimal in-memory S3 client supporting only what backfill calls."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.upload_count = 0

    def add(self, key: str, content: bytes) -> None:
        self.store[key] = content

    def put(self, key: str, content: bytes) -> None:
        self.store[key] = content
        self.upload_count += 1

    def get(self, key: str) -> bytes:
        return self.store[key]

    # boto3-compatible paginator surface
    def get_paginator(self, op_name: str) -> "_FakePaginator":
        assert op_name == "list_objects_v2"
        return _FakePaginator(self.store)


class _FakePaginator:
    def __init__(self, store: dict[str, bytes]) -> None:
        self.store = store

    def paginate(self, *, Bucket: str, Prefix: str) -> Any:  # noqa: N803
        contents = [
            {"Key": k, "Size": len(v)}
            for k, v in self.store.items()
            if k.startswith(Prefix)
        ]
        return [{"Contents": contents}]


def _bundle_with_config(*, config: dict, metrics: dict, embedding_dim: int) -> bytes:
    """Build a model bundle.zip carrying config.json, metrics.json, and a 2D embeddings npz."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("config.json", json.dumps(config))
        zf.writestr("metrics.json", json.dumps(metrics))
        npz_buf = io.BytesIO()
        np.savez_compressed(
            npz_buf,
            oracle_ids=np.asarray(["o1"]),
            face_ixs=np.asarray([0], dtype=np.int32),
            embeddings=np.asarray([[0.0] * embedding_dim], dtype=np.float32),
        )
        zf.writestr("embeddings/embeddings.npz", npz_buf.getvalue())
    return buf.getvalue()


def _training_dataset_bytes(*, version: int = 5) -> bytes:
    return json.dumps(
        {
            "version": version,
            "face_texts": [{"oracle_id": "o1", "face_ix": 0, "name": "X", "text": "x"}],
            "pair_ids": [],
            "direct_text_pairs": [],
            "template_query_examples": 0,
            "llm_query_examples": 0,
            "metadata": {"semantic_data_version": 11},
        }
    ).encode("utf-8")


@pytest.fixture()
def fake_s3(monkeypatch) -> _FakeS3:
    s3 = _FakeS3()

    monkeypatch.setattr("ot_backend.semantic.manifest_backfill.artifact_bucket_client", lambda: s3)
    monkeypatch.setattr("ot_backend.semantic.manifest_backfill.artifact_bucket_name", lambda: "test-bucket")
    monkeypatch.setattr(
        "ot_backend.semantic.manifest_backfill.download_artifact_bytes",
        lambda *, object_key: s3.get(object_key),
    )
    monkeypatch.setattr(
        "ot_backend.semantic.manifest_backfill.upload_artifact_bytes",
        lambda *, object_key, content_bytes, content_type: s3.put(object_key, content_bytes),
    )
    return s3


def test_backfill_upgrades_v1_model_manifest(fake_s3) -> None:
    model_id = "m1"
    bundle_key = f"semantic-registry/models/{model_id}/bundle.zip"
    manifest_key = f"semantic-registry/models/{model_id}/manifest.json"

    fake_s3.add(
        bundle_key,
        _bundle_with_config(
            config={"base_model": "all-MiniLM-L6-v2", "embedding_dim": 384, "epochs": 1},
            metrics={"loss": 0.42},
            embedding_dim=384,
        ),
    )
    fake_s3.add(manifest_key, b'{"version": 1, "bundle": {}}')

    fake_s3.upload_count = 0  # reset to count only sync writes
    report = manifest_backfill.backfill_manifests()

    assert report.models_upgraded == 1
    assert report.models_skipped == 0
    assert fake_s3.upload_count == 1  # only the manifest was rewritten

    upgraded = json.loads(fake_s3.get(manifest_key).decode("utf-8"))
    assert upgraded["version"] == SEMANTIC_MANIFEST_VERSION
    assert upgraded["base_model"] == "all-MiniLM-L6-v2"
    assert upgraded["embedding_dim"] == 384
    assert upgraded["config"]["epochs"] == 1
    assert upgraded["metrics"]["loss"] == 0.42


def test_backfill_upgrades_v1_dataset_manifest(fake_s3) -> None:
    dataset_id = "d1"
    dataset_key = f"semantic-registry/datasets/{dataset_id}/training-dataset.json"
    manifest_key = f"semantic-registry/datasets/{dataset_id}/manifest.json"

    fake_s3.add(dataset_key, _training_dataset_bytes())
    fake_s3.add(manifest_key, b'{"version": 1, "augmentation_mode": "none"}')

    fake_s3.upload_count = 0
    report = manifest_backfill.backfill_manifests()

    assert report.datasets_upgraded == 1
    assert report.datasets_skipped == 0
    assert fake_s3.upload_count == 1

    upgraded = json.loads(fake_s3.get(manifest_key).decode("utf-8"))
    assert upgraded["version"] == SEMANTIC_MANIFEST_VERSION
    assert upgraded["dataset_metrics"]["face_count"] == 1
    assert upgraded["source_semantic_data_version"] == 11


def test_backfill_is_idempotent(fake_s3) -> None:
    model_id = "m1"
    bundle_key = f"semantic-registry/models/{model_id}/bundle.zip"
    manifest_key = f"semantic-registry/models/{model_id}/manifest.json"

    fake_s3.add(
        bundle_key,
        _bundle_with_config(
            config={"base_model": "x", "embedding_dim": 384},
            metrics={},
            embedding_dim=384,
        ),
    )
    # First run upgrades, second run sees v2 manifest and skips.
    manifest_backfill.backfill_manifests()
    fake_s3.upload_count = 0
    report = manifest_backfill.backfill_manifests()

    assert report.models_upgraded == 0
    assert report.models_skipped == 1
    assert fake_s3.upload_count == 0


def test_backfill_creates_manifest_when_absent(fake_s3) -> None:
    model_id = "m2"
    bundle_key = f"semantic-registry/models/{model_id}/bundle.zip"
    manifest_key = f"semantic-registry/models/{model_id}/manifest.json"

    fake_s3.add(
        bundle_key,
        _bundle_with_config(
            config={"base_model": "minilm", "embedding_dim": 384},
            metrics={},
            embedding_dim=384,
        ),
    )

    report = manifest_backfill.backfill_manifests()

    assert report.models_upgraded == 1
    assert manifest_key in fake_s3.store
    upgraded = json.loads(fake_s3.get(manifest_key).decode("utf-8"))
    assert upgraded["version"] == SEMANTIC_MANIFEST_VERSION


def test_backfill_skips_models_without_bundle(fake_s3) -> None:
    model_id = "m3"
    fake_s3.add(f"semantic-registry/models/{model_id}/manifest.json", b'{"version": 1}')

    report = manifest_backfill.backfill_manifests()

    assert report.models_upgraded == 0
    assert report.models_skipped == 1


# ---------------------------------------------------------------------------
# Restore-from-manifest path
#
# When the TUI rehydrates a SemanticModel from a v2 manifest, the row's
# config_json must carry `semantic_data_version` (and `dataset_metadata`) so
# promotion's staleness check (model_promotion._get_model_source_data_version)
# accepts it. Without this the operator gets a "no source semantic data
# version recorded" error on the very first promote of a restored model.
# ---------------------------------------------------------------------------


def test_restore_from_manifest_populates_staleness_fields(monkeypatch) -> None:
    from ot_backend.core.database import SessionLocal
    from ot_backend.core.db_init import init_db
    from ot_backend.core.models import SemanticModel, SemanticModelArtifact
    from ot_backend.semantic.model_promotion import _get_model_source_data_version
    from ot_backend.tui.app import _S3Object, _import_model_from_s3

    manifest_payload = json.dumps(
        {
            "version": SEMANTIC_MANIFEST_VERSION,
            "base_model": "all-MiniLM-L6-v2",
            "embedding_dim": 384,
            "config": {"epochs": 3},
            "metrics": {"loss": 0.1},
            "source_semantic_data_version": 11,
            "dataset_metadata": {"semantic_data_version": 11, "augmentation_mode": "none"},
        }
    ).encode("utf-8")

    monkeypatch.setattr(
        "ot_backend.tui.app.download_artifact_bytes",
        lambda *, object_key: manifest_payload,
        raising=False,
    )
    # _load_manifest in tui/app.py imports download_artifact_bytes locally; patch the source module too.
    monkeypatch.setattr(
        "ot_backend.semantic.artifacts.download_artifact_bytes",
        lambda *, object_key: manifest_payload,
    )

    init_db()
    with SessionLocal() as db:
        db.query(SemanticModelArtifact).delete()
        db.query(SemanticModel).delete()
        db.commit()

    model_id = "restored-test-1"
    manifest_key = f"semantic-registry/models/{model_id}/manifest.json"
    files = {
        "manifest.json": _S3Object(key=manifest_key, size=len(manifest_payload)),
        "bundle.zip": _S3Object(key=f"semantic-registry/models/{model_id}/bundle.zip", size=1024),
    }

    assert _import_model_from_s3(model_id, files) is True

    with SessionLocal() as db:
        model = db.get(SemanticModel, model_id)
        assert model is not None
        assert model.config_json is not None
        assert model.config_json.get("semantic_data_version") == 11
        assert model.config_json.get("dataset_metadata", {}).get("semantic_data_version") == 11
        # Promotion's staleness check finds the version through the same getter.
        assert _get_model_source_data_version(model) == 11

        db.query(SemanticModelArtifact).delete()
        db.query(SemanticModel).delete()
        db.commit()
