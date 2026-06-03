from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import init_db
from ot_backend.core.models import (
    Card,
    CardFace,
    CardRaw,
    SemanticModel,
    SemanticModelArtifact,
    SemanticModelEmbedding,
    SystemMetadata,
)
from ot_backend.semantic import index
from ot_backend.semantic.artifacts import (
    SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
    SEMANTIC_MODEL_ARTIFACT_KIND_EVAL_JSON,
    SEMANTIC_MODEL_ARTIFACT_KIND_MANIFEST_JSON,
    SEMANTIC_MODEL_ARTIFACT_KIND_TRAINING_DATASET,
)
from ot_backend.semantic.bundle_registration import register_model_bundle_bytes
from ot_backend.semantic.model_promotion import (
    _populate_model_embeddings,
    promote_semantic_model,
    store_model_embeddings,
)
from ot_backend.semantic.model_registry import (
    SEMANTIC_MODEL_STATUS_ACTIVE,
    SEMANTIC_MODEL_STATUS_EMBEDDING,
    SEMANTIC_MODEL_STATUS_READY,
    bundle_model_directory,
    materialize_semantic_model,
)
from ot_backend.semantic.semantic_state import bump_semantic_data_version, get_active_model_data_version


def _make_model_bundle(tmp_path, *, include_pytorch: bool = True, include_embeddings: bool = True):
    model_root = tmp_path / "semantic-model"
    onnx_root = model_root / "models" / "onnx"
    pooling_dir = onnx_root / "1_Pooling"
    pooling_dir.mkdir(parents=True)
    (onnx_root / "onnx").mkdir(parents=True)
    (onnx_root / "onnx" / "model.onnx").write_bytes(b"onnx")
    (onnx_root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (pooling_dir / "config.json").write_text('{"pooling_mode_mean_tokens": true}', encoding="utf-8")
    (model_root / "models" / "pytorch").mkdir(parents=True)
    (model_root / "models" / "pytorch" / "config.json").write_text("{}", encoding="utf-8")
    embeddings_dir = model_root / "embeddings"
    embeddings_dir.mkdir(parents=True)
    np.savez_compressed(
        embeddings_dir / "embeddings.npz",
        oracle_ids=np.asarray(["o1", "o2"]),
        face_ixs=np.asarray([0, 0], dtype=np.int32),
        embeddings=np.asarray([[1.0] + [0.0] * 383, [0.0, 1.0] + [0.0] * 382], dtype=np.float32),
    )
    training_dir = model_root / "training"
    training_dir.mkdir(parents=True)
    (training_dir / "training-dataset.json").write_text(
        '{"version": 5, "face_texts": [{"oracle_id": "o1", "face_ix": 0, "name": "Shock", "text": "deal damage"}], "pair_ids": [], "direct_text_pairs": [], "simcse_examples": 0, "tag_pair_examples": 0, "tag_desc_pair_examples": 0, "template_query_examples": 0, "metadata": {"semantic_data_version": 1}}',
        encoding="utf-8",
    )
    eval_dir = model_root / "eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "eval.json").write_text(
        '{"version": 1, "summary": {"query_count": 1, "top1_hits": 1, "top3_hits": 1, "top5_hits": 1, "top1_rate": 1.0, "top3_rate": 1.0, "top5_rate": 1.0, "mrr": 1.0}, "queries": []}',
        encoding="utf-8",
    )
    (model_root / "config.json").write_text('{"epochs": 1}', encoding="utf-8")
    (model_root / "metrics.json").write_text('{"loss": 0.1}', encoding="utf-8")
    (model_root / "manifest.json").write_text(
        '{"version": 1, "bundle": {"has_onnx_model": true, "has_pytorch_model": true, "has_precomputed_embeddings": true, "has_training_dataset": true, "has_eval_json": true}, "source_semantic_data_version": 1, "dataset_metadata": {"semantic_data_version": 1}}',
        encoding="utf-8",
    )
    return bundle_model_directory(model_root)


def _reset_registry_tables() -> None:
    with SessionLocal() as db:
        db.query(SemanticModelEmbedding).delete()
        db.query(SemanticModelArtifact).delete()
        db.query(SemanticModel).delete()
        db.query(SystemMetadata).filter(SystemMetadata.key.in_(["semantic_data", "semantic_dataset_export", "semantic_active_model"])).delete()
        db.commit()

    _seed_minimal_cards()


def _seed_minimal_cards() -> None:
    """Seed the minimal (oracle_id, face_ix) rows referenced by promotion tests
    so that `semantic_model_embeddings` FK constraints pass on Postgres.
    """
    with SessionLocal() as db:
        if db.query(CardFace).filter(CardFace.oracle_id == "o1").count() > 0:
            return

        db.query(CardFace).delete()
        db.query(Card).delete()
        db.query(CardRaw).delete()
        db.commit()

        for oracle_id, scryfall_id, name in (("o1", "s1", "Lightning Bolt"), ("o2", "s2", "Shock")):
            db.add(
                CardRaw(
                    id=scryfall_id,
                    oracle_id=oracle_id,
                    name=name,
                    lang="en",
                    layout="normal",
                    color_identity=["R"],
                    keywords=[],
                    legalities={},
                    rarity="common",
                    set_code="tst",
                    set_id="set-tst",
                    set_name="Test Set",
                    set_type="expansion",
                    collector_number=scryfall_id,
                    games=["paper"],
                    finishes=["nonfoil"],
                )
            )
        db.flush()

        for oracle_id, scryfall_id, name in (("o1", "s1", "Lightning Bolt"), ("o2", "s2", "Shock")):
            db.add(
                Card(
                    oracle_id=oracle_id,
                    scryfall_id=scryfall_id,
                    name=name,
                    layout="normal",
                    rarity="common",
                    legalities={},
                    color_identity=["R"],
                )
            )
        db.flush()

        db.add_all(
            [
                CardFace(oracle_id="o1", face_ix=0, name="Lightning Bolt", type_line="Instant", colors=["R"]),
                CardFace(oracle_id="o2", face_ix=0, name="Shock", type_line="Instant", colors=["R"]),
            ]
        )
        db.commit()


def _mock_artifact_download(monkeypatch, bundle: bytes) -> None:
    monkeypatch.setattr("ot_backend.semantic.model_registry.download_artifact_bytes", lambda *, object_key: bundle)


def _create_model_with_bundle_artifact(
    db,
    *,
    slug: str,
    base_model: str,
    bundle: bytes,
    status: str = "uploaded",
    is_active: bool = False,
    config_json: dict[str, object] | None = None,
    metrics_json: dict[str, object] | None = None,
) -> SemanticModel:
    model = SemanticModel(
        slug=slug,
        base_model=base_model,
        status=status,
        is_active=is_active,
        embedding_dim=384,
        config_json=config_json,
        metrics_json=metrics_json,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    db.add(
        SemanticModelArtifact(
            model_id=model.id,
            artifact_kind=SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
            object_key=f"semantic-registry/{model.id}/bundle.zip",
            sha256=hashlib.sha256(bundle).hexdigest(),
            size_bytes=len(bundle),
            content_type="application/zip",
            metadata_json={"format": "zip"},
        )
    )
    db.commit()
    db.refresh(model)
    return model


def test_materialize_semantic_model_extracts_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_TEMP_DIR", str(tmp_path / "semantic-cache"))
    bundle = _make_model_bundle(tmp_path)
    _mock_artifact_download(monkeypatch, bundle)
    init_db()
    _reset_registry_tables()

    with SessionLocal() as db:
        model = _create_model_with_bundle_artifact(
            db,
            slug="materialize-test",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            bundle=bundle,
        )
        model_root, _bundle_root = materialize_semantic_model(model)

    assert (model_root / "onnx" / "model.onnx").exists()
    assert (model_root / "tokenizer.json").exists()


def test_register_model_bundle_bytes_records_dataset_and_manifest_artifacts(tmp_path, monkeypatch):
    uploaded: dict[str, bytes] = {}
    bundle = _make_model_bundle(tmp_path, include_pytorch=True, include_embeddings=True)
    dataset_bytes = b'{"version": 5, "metadata": {"semantic_data_version": 7}}'
    monkeypatch.setattr(
        "ot_backend.semantic.artifacts.upload_artifact_bytes",
        lambda *, object_key, content_bytes, content_type: uploaded.__setitem__(object_key, content_bytes),
    )
    init_db()
    _reset_registry_tables()

    with SessionLocal() as db:
        model = register_model_bundle_bytes(
            db,
            slug="artifact-tracked",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            artifact_bundle_bytes=bundle,
            dataset_bytes=dataset_bytes,
            augmentation_mode="none",
            source_semantic_data_version=None,
            config_json=None,
            metrics_json=None,
        )
        model_id = model.id

    with SessionLocal() as db:
        model = db.get(SemanticModel, model_id)
        assert model is not None
        artifacts = db.query(SemanticModelArtifact).filter(SemanticModelArtifact.model_id == model_id).all()
        artifact_keys = {artifact.artifact_kind: artifact.object_key for artifact in artifacts}
        assert artifact_keys["bundle_zip"] in uploaded
        assert artifact_keys["training_dataset"] in uploaded
        assert artifact_keys["eval_json"] in uploaded
        assert artifact_keys["manifest_json"] in uploaded
        assert {artifact.artifact_kind for artifact in artifacts} == {
            SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
            SEMANTIC_MODEL_ARTIFACT_KIND_TRAINING_DATASET,
            SEMANTIC_MODEL_ARTIFACT_KIND_EVAL_JSON,
            SEMANTIC_MODEL_ARTIFACT_KIND_MANIFEST_JSON,
        }


def test_register_model_bundle_bytes_rejects_embedding_dimension_mismatch(tmp_path, monkeypatch):
    bundle_root = tmp_path / "semantic-model-mismatch"
    uploaded: dict[str, bytes] = {}
    _make_model_bundle(tmp_path)
    monkeypatch.setattr(
        "ot_backend.semantic.artifacts.upload_artifact_bytes",
        lambda *, object_key, content_bytes, content_type: uploaded.__setitem__(object_key, content_bytes),
    )
    bundle_root.mkdir(parents=True, exist_ok=True)
    model_root = bundle_root / "semantic-model"
    onnx_root = model_root / "models" / "onnx"
    pooling_dir = onnx_root / "1_Pooling"
    pooling_dir.mkdir(parents=True)
    (onnx_root / "onnx").mkdir(parents=True)
    (onnx_root / "onnx" / "model.onnx").write_bytes(b"onnx")
    (onnx_root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (pooling_dir / "config.json").write_text('{"pooling_mode_mean_tokens": true}', encoding="utf-8")
    (model_root / "models" / "pytorch").mkdir(parents=True)
    (model_root / "models" / "pytorch" / "config.json").write_text("{}", encoding="utf-8")
    (model_root / "embeddings").mkdir(parents=True)
    np.savez_compressed(
        model_root / "embeddings" / "embeddings.npz",
        oracle_ids=np.asarray(["o1"]),
        face_ixs=np.asarray([0], dtype=np.int32),
        embeddings=np.asarray([[1.0] + [0.0] * 767], dtype=np.float32),
    )
    (model_root / "training").mkdir(parents=True)
    (model_root / "training" / "training-dataset.json").write_text(
        '{"version": 5, "face_texts": [], "pair_ids": [], "direct_text_pairs": [], "simcse_examples": 0, "tag_pair_examples": 0, "tag_desc_pair_examples": 0, "template_query_examples": 0, "metadata": {"semantic_data_version": 1}}',
        encoding="utf-8",
    )
    (model_root / "eval").mkdir(parents=True)
    (model_root / "eval" / "eval.json").write_text(
        '{"version": 1, "summary": {"query_count": 1, "top1_hits": 1, "top3_hits": 1, "top5_hits": 1, "top1_rate": 1.0, "top3_rate": 1.0, "top5_rate": 1.0, "mrr": 1.0}, "queries": []}',
        encoding="utf-8",
    )
    (model_root / "config.json").write_text("{}", encoding="utf-8")
    (model_root / "metrics.json").write_text("{}", encoding="utf-8")
    (model_root / "manifest.json").write_text("{}", encoding="utf-8")
    bundle = bundle_model_directory(model_root)
    init_db()
    _reset_registry_tables()

    with SessionLocal() as db:
        try:
            register_model_bundle_bytes(
                db,
                slug="artifact-mismatch",
                base_model="sentence-transformers/all-MiniLM-L6-v2",
                artifact_bundle_bytes=bundle,
                augmentation_mode="none",
            )
        except ValueError as exc:
            assert "does not match expected dimension 384" in str(exc)
        else:
            raise AssertionError("Expected embedding dimension mismatch to be rejected.")


def test_run_semantic_model_promotion_activates_candidate_and_stores_embeddings(tmp_path, monkeypatch):
    bundle = _make_model_bundle(tmp_path)
    _mock_artifact_download(monkeypatch, bundle)
    init_db()
    _reset_registry_tables()
    with SessionLocal() as db:
        bump_semantic_data_version(db)

    with SessionLocal() as db:
        active = _create_model_with_bundle_artifact(
            db,
            slug="current",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            bundle=bundle,
            status="active",
            is_active=True,
            config_json={"semantic_data_version": 1},
        )
        candidate = _create_model_with_bundle_artifact(
            db,
            slug="candidate",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            bundle=bundle,
            config_json={"semantic_data_version": 1},
        )
        candidate_id = candidate.id
        active_id = active.id

    monkeypatch.setattr(
        "ot_backend.semantic.model_promotion._populate_model_embeddings",
        lambda model_id, *_args, **_kwargs: (
            store_model_embeddings(
                model_id,
                [
                    ("o1", 0, [1.0] + [0.0] * 383),
                    ("o2", 0, [0.0, 1.0] + [0.0] * 382),
                ],
            ),
            "onnx",
        ),
    )

    assert promote_semantic_model(candidate_id) is True

    with SessionLocal() as db:
        candidate = db.get(SemanticModel, candidate_id)
        active = db.get(SemanticModel, active_id)
        assert candidate is not None
        assert active is not None
        assert candidate.status == SEMANTIC_MODEL_STATUS_ACTIVE
        assert candidate.is_active is True
        assert active.status == SEMANTIC_MODEL_STATUS_READY
        assert active.is_active is False
        embeddings = db.query(SemanticModelEmbedding).filter(SemanticModelEmbedding.model_id == candidate_id).all()
        assert len(embeddings) == 2
        assert get_active_model_data_version(db) == 1
        assert candidate.metrics_json is not None
        assert candidate.metrics_json["promotion_embedding_backend"] == "onnx"


def test_run_semantic_model_promotion_rejects_stale_candidate(tmp_path, monkeypatch):
    bundle = _make_model_bundle(tmp_path)
    _mock_artifact_download(monkeypatch, bundle)
    init_db()
    _reset_registry_tables()
    with SessionLocal() as db:
        bump_semantic_data_version(db)
        bump_semantic_data_version(db)

    with SessionLocal() as db:
        candidate = _create_model_with_bundle_artifact(
            db,
            slug="stale-candidate",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            bundle=bundle,
            config_json={"semantic_data_version": 1},
        )
        candidate_id = candidate.id

    try:
        promote_semantic_model(candidate_id)
    except RuntimeError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("Expected promote_semantic_model to raise on stale candidate.")

    with SessionLocal() as db:
        candidate = db.get(SemanticModel, candidate_id)
        assert candidate is not None
        # Pre-flight rejection leaves the model untouched (status unchanged).
        assert candidate.status == "uploaded"
        assert candidate.is_active is False


def test_run_semantic_model_promotion_rejects_candidate_without_source_version(tmp_path, monkeypatch):
    bundle = _make_model_bundle(tmp_path)
    _mock_artifact_download(monkeypatch, bundle)
    init_db()
    _reset_registry_tables()

    with SessionLocal() as db:
        bump_semantic_data_version(db)

    with SessionLocal() as db:
        candidate = _create_model_with_bundle_artifact(
            db,
            slug="missing-version",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            bundle=bundle,
            config_json={},
        )
        candidate_id = candidate.id

    try:
        promote_semantic_model(candidate_id)
    except RuntimeError as exc:
        assert "no source semantic data version" in str(exc)
    else:
        raise AssertionError("Expected promote_semantic_model to raise on candidate missing source version.")

    with SessionLocal() as db:
        candidate = db.get(SemanticModel, candidate_id)
        assert candidate is not None
        assert candidate.status == "uploaded"
        assert candidate.is_active is False


def test_promote_semantic_model_releases_lock_when_model_is_missing(tmp_path, monkeypatch):
    bundle = _make_model_bundle(tmp_path)
    _mock_artifact_download(monkeypatch, bundle)
    init_db()
    _reset_registry_tables()
    with SessionLocal() as db:
        bump_semantic_data_version(db)

    with SessionLocal() as db:
        candidate = _create_model_with_bundle_artifact(
            db,
            slug="lock-release",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            bundle=bundle,
            config_json={"semantic_data_version": 1},
        )
        candidate_id = candidate.id

    monkeypatch.setattr(
        "ot_backend.semantic.model_promotion._populate_model_embeddings",
        lambda *_args, **_kwargs: (0, "onnx"),
    )

    try:
        promote_semantic_model("00000000-0000-0000-0000-000000000000")
    except KeyError:
        pass
    else:
        raise AssertionError("Expected missing model promotion to raise KeyError.")

    assert promote_semantic_model(candidate_id) is True

    with SessionLocal() as db:
        candidate = db.get(SemanticModel, candidate_id)
        assert candidate is not None
        assert candidate.status == SEMANTIC_MODEL_STATUS_ACTIVE


def test_promote_semantic_model_blocks_when_another_is_embedding(tmp_path):
    bundle = _make_model_bundle(tmp_path)
    init_db()
    _reset_registry_tables()
    with SessionLocal() as db:
        bump_semantic_data_version(db)

    with SessionLocal() as db:
        first = _create_model_with_bundle_artifact(
            db,
            slug="candidate-one",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            bundle=bundle,
            status=SEMANTIC_MODEL_STATUS_EMBEDDING,
            config_json={"semantic_data_version": 1},
        )
        second = _create_model_with_bundle_artifact(
            db,
            slug="candidate-two",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            bundle=bundle,
            config_json={"semantic_data_version": 1},
        )
        del first  # unused after setup; status=EMBEDDING row is what matters
        second_id = second.id

    try:
        promote_semantic_model(second_id)
    except RuntimeError as exc:
        assert "already running" in str(exc)
    else:
        raise AssertionError("Expected second promotion to be blocked.")


def test_single_active_model_enforced_by_db_constraint(tmp_path):
    from sqlalchemy.exc import IntegrityError

    init_db()
    _reset_registry_tables()

    with SessionLocal() as db:
        db.add(SemanticModel(slug="active-a", base_model="m", status="active", is_active=True, embedding_dim=384))
        db.add(SemanticModel(slug="active-b", base_model="m", status="active", is_active=True, embedding_dim=384))
        raised = False
        try:
            db.commit()
        except IntegrityError:
            raised = True
            db.rollback()
        assert raised, "DB must reject a second active semantic model"

    with SessionLocal() as db:
        assert db.query(SemanticModel).filter(SemanticModel.is_active.is_(True)).count() == 0


def test_materialize_rejects_sha256_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_TEMP_DIR", str(tmp_path / "semantic-cache"))
    bundle = _make_model_bundle(tmp_path)
    # Download returns the real bundle, but the recorded sha256 is wrong.
    _mock_artifact_download(monkeypatch, bundle)
    init_db()
    _reset_registry_tables()

    with SessionLocal() as db:
        model = SemanticModel(slug="bad-sha", base_model="m", status="uploaded", is_active=False, embedding_dim=384)
        db.add(model)
        db.commit()
        db.refresh(model)
        db.add(
            SemanticModelArtifact(
                model_id=model.id,
                artifact_kind=SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
                object_key=f"semantic-registry/{model.id}/bundle.zip",
                sha256="0" * 64,
                size_bytes=len(bundle),
                content_type="application/zip",
                metadata_json={"format": "zip"},
            )
        )
        db.commit()
        db.refresh(model)

        try:
            materialize_semantic_model(model)
        except ValueError as exc:
            assert "integrity" in str(exc).lower()
        else:
            raise AssertionError("Expected sha256 mismatch to be rejected.")


def test_safe_extractall_rejects_path_traversal(tmp_path):
    import io
    import zipfile

    from ot_backend.semantic.model_registry import _safe_extractall

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", b"pwned")
    buf.seek(0)

    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with zipfile.ZipFile(buf) as archive:
        try:
            _safe_extractall(archive, extract_dir)
        except ValueError as exc:
            assert "Unsafe path" in str(exc)
        else:
            raise AssertionError("Expected zip-slip member to be rejected.")

    assert not (tmp_path / "escape.txt").exists()


def test_register_bundle_cleans_s3_and_rolls_back_on_failure(tmp_path, monkeypatch):
    bundle = _make_model_bundle(tmp_path)
    dataset_bytes = b'{"version": 5, "metadata": {"semantic_data_version": 1}}'
    uploaded: dict[str, bytes] = {}
    deleted: list[str] = []

    def fake_upload(*, object_key, content_bytes, content_type):
        if object_key.endswith("manifest.json"):
            raise RuntimeError("boom on manifest upload")
        uploaded[object_key] = content_bytes

    monkeypatch.setattr("ot_backend.semantic.artifacts.upload_artifact_bytes", fake_upload)
    monkeypatch.setattr(
        "ot_backend.semantic.bundle_registration.delete_artifact_object",
        lambda *, object_key: deleted.append(object_key),
    )
    init_db()
    _reset_registry_tables()

    with SessionLocal() as db:
        try:
            register_model_bundle_bytes(
                db,
                slug="atomic-fail",
                base_model="sentence-transformers/all-MiniLM-L6-v2",
                artifact_bundle_bytes=bundle,
                dataset_bytes=dataset_bytes,
                augmentation_mode="none",
                source_semantic_data_version=1,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Expected registration to fail on manifest upload.")

    with SessionLocal() as db:
        assert db.query(SemanticModel).filter(SemanticModel.slug == "atomic-fail").count() == 0

    # The objects uploaded before the failure are cleaned up (no orphans).
    assert any(key.endswith("bundle.zip") for key in deleted)
    assert any(key.endswith("training-dataset.json") for key in deleted)


def test_populate_model_embeddings_prefers_precomputed_archive(monkeypatch, tmp_path):
    bundle_root = tmp_path / "bundle"
    onnx_root = bundle_root / "models" / "onnx"
    (onnx_root / "onnx").mkdir(parents=True)
    (onnx_root / "onnx" / "model.onnx").write_bytes(b"onnx")
    (bundle_root / "models" / "pytorch").mkdir(parents=True)
    embeddings_dir = bundle_root / "embeddings"
    embeddings_dir.mkdir(parents=True)
    archive_path = embeddings_dir / "embeddings.npz"
    archive_path.write_bytes(b"npz")

    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        "ot_backend.semantic.model_promotion._store_precomputed_embeddings_from_archive",
        lambda _model_id, path, batch_size: calls.append(("precomputed", path)) or 2,
    )
    monkeypatch.setattr(
        "ot_backend.semantic.model_promotion._compute_and_store_embeddings_from_pytorch_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pytorch path should not run")),
    )
    monkeypatch.setattr(
        "ot_backend.semantic.model_promotion._compute_and_store_embeddings_from_onnx_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("onnx path should not run")),
    )

    count, backend = _populate_model_embeddings(12, onnx_root, bundle_root, batch_size=32)

    assert (count, backend) == (2, "precomputed")
    assert calls == [("precomputed", archive_path)]


def test_populate_model_embeddings_prefers_pytorch_before_onnx(monkeypatch, tmp_path):
    bundle_root = tmp_path / "bundle"
    onnx_root = bundle_root / "models" / "onnx"
    (onnx_root / "onnx").mkdir(parents=True)
    (onnx_root / "onnx" / "model.onnx").write_bytes(b"onnx")
    pytorch_path = bundle_root / "models" / "pytorch"
    pytorch_path.mkdir(parents=True)

    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        "ot_backend.semantic.model_promotion._compute_and_store_embeddings_from_pytorch_model",
        lambda _model_id, path, batch_size: calls.append(("pytorch", path)) or 3,
    )
    monkeypatch.setattr(
        "ot_backend.semantic.model_promotion._compute_and_store_embeddings_from_onnx_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("onnx path should not run")),
    )

    count, backend = _populate_model_embeddings(12, onnx_root, bundle_root, batch_size=32)

    assert (count, backend) == (3, "pytorch")
    assert calls == [("pytorch", pytorch_path)]


def test_get_semantic_index_prefers_active_db_model(monkeypatch, tmp_path):
    bundle = _make_model_bundle(tmp_path)
    init_db()
    _reset_registry_tables()
    _mock_artifact_download(monkeypatch, bundle)

    with SessionLocal() as db:
        model = _create_model_with_bundle_artifact(
            db,
            slug="db-active",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            bundle=bundle,
            status="active",
            is_active=True,
        )
        model_id = model.id

    index._index = None
    index._last_refresh_check = 0.0

    import_calls: list[str] = []
    tokenizer_paths: list[str] = []
    session_paths: list[str] = []

    class FakeEncoding:
        def __init__(self, ids, attention_mask, type_ids):
            self.ids = ids
            self.attention_mask = attention_mask
            self.type_ids = type_ids

    class FakeTokenizer:
        @classmethod
        def from_file(cls, path: str):
            tokenizer_paths.append(path)
            return cls()

        def enable_truncation(self, max_length: int) -> None:
            assert max_length == 512

        def enable_padding(self, pad_id: int, pad_token: str) -> None:
            assert pad_id == 0
            assert pad_token == "[PAD]"

        def token_to_id(self, token: str):
            assert token == "[PAD]"
            return 0

        def encode_batch(self, texts):
            assert texts == ["Deal damage to any target."]
            return [FakeEncoding(ids=[101, 102], attention_mask=[1, 1], type_ids=[0, 0])]

    class FakeSessionOptions:
        def __init__(self) -> None:
            self.log_severity_level = 0
            self.intra_op_num_threads = 0
            self.inter_op_num_threads = 0
            self.enable_cpu_mem_arena = True
            self.enable_mem_pattern = True

    class FakeInferenceSession:
        def __init__(self, path: str, *, sess_options: FakeSessionOptions, providers: list[str]) -> None:
            session_paths.append(path)
            assert providers == ["CPUExecutionProvider"]
            assert sess_options.log_severity_level == 3
            assert sess_options.intra_op_num_threads == 2
            assert sess_options.inter_op_num_threads == 3
            assert sess_options.enable_cpu_mem_arena is False
            assert sess_options.enable_mem_pattern is False

        def get_inputs(self):
            return [SimpleNamespace(name="input_ids"), SimpleNamespace(name="attention_mask")]

        def run(self, _output_names, inputs):
            import numpy as np

            assert inputs["input_ids"].shape == (1, 2)
            return [np.asarray([[[1.0, 0.0], [0.0, 1.0]]], dtype=np.float32)]

    def fake_import_module(module_name: str):
        import_calls.append(module_name)
        if module_name == "onnxruntime":
            return SimpleNamespace(
                InferenceSession=FakeInferenceSession,
                SessionOptions=FakeSessionOptions,
                GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_BASIC="ORT_ENABLE_BASIC"),
            )
        if module_name == "tokenizers":
            return SimpleNamespace(Tokenizer=FakeTokenizer)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setenv("SEMANTIC_ACTIVE_MODEL_POLL_SECONDS", "0")
    monkeypatch.setenv("SEMANTIC_ONNX_INTRA_OP_THREADS", "2")
    monkeypatch.setenv("SEMANTIC_ONNX_INTER_OP_THREADS", "3")
    monkeypatch.setenv("SEMANTIC_TEMP_DIR", str(tmp_path / "semantic-cache"))
    monkeypatch.setattr("ot_backend.semantic.index.import_module", fake_import_module)
    monkeypatch.setattr("ot_backend.semantic.index.configure_huggingface_env", lambda: None)

    semantic_index = index.get_semantic_index()

    assert semantic_index is not None
    assert semantic_index.model_id == model_id
    assert semantic_index.encode_query("Deal damage to any target.") == [0.7071067690849304, 0.7071067690849304]
    assert len(tokenizer_paths) == 1
    expected_digest_prefix = hashlib.sha256(bundle).hexdigest()[:12]
    assert tokenizer_paths[0].endswith(
        f"semantic-model-{model_id}-{expected_digest_prefix}/models/onnx/tokenizer.json"
    )
    assert len(session_paths) == 1
    assert session_paths[0].endswith("onnx/model.onnx")
    assert import_calls == ["onnxruntime", "tokenizers"]
    index._index = None
    index._last_refresh_check = 0.0
