from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace


def _fake_modal_module(**fns: object) -> SimpleNamespace:
    @contextmanager
    def _run(**_kwargs: object):
        yield

    return SimpleNamespace(app=SimpleNamespace(run=_run), **fns)

from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import init_db
from ot_backend.core.models import (
    SemanticDataset,
    SemanticDatasetArtifact,
    SemanticJob,
    SemanticModel,
    SemanticModelArtifact,
    SemanticModelEmbedding,
)
from ot_backend.semantic import dataset_worker, promote_worker, train_worker
from ot_backend.semantic.artifacts import (
    SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON,
    semantic_dataset_artifact_object_key,
    semantic_model_artifact_object_key,
)
from ot_backend.semantic.base_model_catalog import get_semantic_base_model
from ot_backend.semantic.semantic_jobs import (
    create_dataset_job,
    create_promote_job,
    create_train_job,
    fail_stale_running_jobs,
    mark_semantic_job_failed,
)


def _reset_tables() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(SemanticJob).delete()
        db.query(SemanticModelEmbedding).delete()
        db.query(SemanticModelArtifact).delete()
        db.query(SemanticDatasetArtifact).delete()
        db.query(SemanticModel).delete()
        db.query(SemanticDataset).delete()
        db.commit()


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _create_dataset(
    *,
    slug: str,
    augmentation_mode: str = "none",
    source_semantic_data_version: int = 1,
) -> str:
    with SessionLocal() as db:
        dataset = SemanticDataset(
            slug=slug,
            status="ready",
            augmentation_mode=augmentation_mode,
            source_semantic_data_version=source_semantic_data_version,
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        db.add(
            SemanticDatasetArtifact(
                dataset_id=dataset.id,
                artifact_kind=SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON,
                object_key=semantic_dataset_artifact_object_key(dataset.id, SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON),
                sha256=hashlib.sha256(b"dataset").hexdigest(),
                size_bytes=len(b"dataset"),
                content_type="application/json",
                metadata_json={"semantic_data_version": source_semantic_data_version},
            )
        )
        db.commit()
        return dataset.id


def _create_model_with_bundle_artifact(
    *,
    slug: str,
    bundle: bytes,
    status: str = "uploaded",
    is_active: bool = False,
    dataset_id: str | None = None,
) -> str:
    with SessionLocal() as db:
        model = SemanticModel(
            slug=slug,
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            status=status,
            is_active=is_active,
            embedding_dim=384,
            dataset_id=dataset_id,
        )
        db.add(model)
        db.commit()
        db.refresh(model)
        db.add(
            SemanticModelArtifact(
                model_id=model.id,
                artifact_kind="bundle_zip",
                object_key=semantic_model_artifact_object_key(model.id, "bundle_zip"),
                sha256=hashlib.sha256(bundle).hexdigest(),
                size_bytes=len(bundle),
                content_type="application/zip",
                metadata_json={"format": "zip"},
            )
        )
        db.commit()
        return model.id


def test_dataset_worker_drains_pending_plain_dataset_job(monkeypatch) -> None:
    _reset_tables()
    dataset_bytes = json.dumps(
        {
            "version": 6,
            "face_texts": [{"oracle_id": "o1", "face_ix": 0, "name": "Shock", "text": "deal damage"}],
            "pair_ids": [],
            "direct_text_pairs": [["burn spell", "deal damage"]],
            "template_query_examples": 1,
            "llm_query_examples": 0,
            "metadata": {"semantic_data_version": 7},
        }
    ).encode("utf-8")

    with SessionLocal() as db:
        job = create_dataset_job(
            db,
            requested_by="olmo",
            dataset_slug="dataset-plain",
            augmentation_mode="none",
        )
        job_id = job.id

    monkeypatch.setattr("ot_backend.semantic.dataset_worker.export_training_dataset_bytes", lambda **_kwargs: dataset_bytes)
    monkeypatch.setattr(
        "ot_backend.semantic.dataset_worker.create_semantic_dataset",
        lambda _db, **kwargs: SimpleNamespace(id=_create_dataset(slug=kwargs["slug"], augmentation_mode=kwargs["augmentation_mode"])),
    )
    monkeypatch.setattr(
        "ot_backend.semantic.dataset_worker.semantic_dataset_artifact_keys",
        lambda _db, dataset_id: {"dataset_json": f"semantic-registry/datasets/{dataset_id}/training-dataset.json"},
    )

    exit_code = dataset_worker.main([])

    assert exit_code == 0
    with SessionLocal() as db:
        job = db.get(SemanticJob, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.dataset_id is not None
        assert job.result_json == {
            "dataset_id": job.dataset_id,
            "dataset_slug": "dataset-plain",
            "artifact_keys": {"dataset_json": f"semantic-registry/datasets/{job.dataset_id}/training-dataset.json"},
        }


def test_dataset_worker_uses_modal_for_llm_augmentation(monkeypatch) -> None:
    _reset_tables()
    remote_calls: list[tuple[object, ...]] = []
    payload_bytes = b'{"version": 1}'
    dataset_bytes = b'{"version": 6, "metadata": {"semantic_data_version": 3}, "llm_query_examples": 3}'

    with SessionLocal() as db:
        job = create_dataset_job(
            db,
            requested_by="olmo",
            dataset_slug="dataset-llm",
            augmentation_mode="llm_queries",
        )
        job_id = job.id

    monkeypatch.setattr("ot_backend.semantic.dataset_worker.export_training_build_payload_bytes", lambda **_kwargs: payload_bytes)
    monkeypatch.setattr("ot_backend.semantic.dataset_worker.modal_client_configured", lambda: True)
    monkeypatch.setattr(
        "ot_backend.semantic.dataset_worker._load_modal_train_module",
        lambda: _fake_modal_module(build_dataset=SimpleNamespace(remote=lambda *args: remote_calls.append(args) or dataset_bytes)),
    )
    monkeypatch.setattr(
        "ot_backend.semantic.dataset_worker.create_semantic_dataset",
        lambda _db, **kwargs: SimpleNamespace(id=_create_dataset(slug=kwargs["slug"], augmentation_mode=kwargs["augmentation_mode"])),
    )
    monkeypatch.setattr(
        "ot_backend.semantic.dataset_worker.semantic_dataset_artifact_keys",
        lambda _db, dataset_id: {"dataset_json": f"semantic-registry/datasets/{dataset_id}/training-dataset.json"},
    )

    exit_code = dataset_worker.main([])

    assert exit_code == 0
    assert remote_calls == [
        (
            payload_bytes,
            "llm_queries",
            {
                "model_name": "Qwen/Qwen2.5-7B-Instruct",
                "max_queries_per_face": 3,
                "max_faces": 2500,
                "min_template_coverage": 2,
                "temperature": 0.6,
                "max_tokens": 500,
            },
        )
    ]
    with SessionLocal() as db:
        job = db.get(SemanticJob, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.dataset_id is not None


def test_train_worker_drains_pending_train_job_and_records_result(monkeypatch) -> None:
    _reset_tables()
    remote_calls: list[tuple[object, ...]] = []
    dataset_bytes = json.dumps({"version": 6, "metadata": {"semantic_data_version": 3}, "llm_query_examples": 0}).encode("utf-8")
    eval_queries_bytes = b'{"queries": []}'
    dataset_id = _create_dataset(slug="dataset-1", augmentation_mode="none", source_semantic_data_version=3)
    registered_model_id: str | None = None

    with SessionLocal() as db:
        job = create_train_job(
            db,
            requested_by="olmo",
            dataset_id=dataset_id,
            model_slug="candidate-1",
            base_model_key="mini-lm-l6-v2",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_dim=384,
            skip_fine_tune=False,
            epochs=3,
            batch_size=8,
            promote_after_register=False,
            embed_batch_size=128,
        )
        job_id = job.id

    def fake_register_model_bundle_bytes(_db, **kwargs):
        nonlocal registered_model_id
        assert kwargs["artifact_bundle_bytes"] == b"bundle-bytes"
        assert kwargs["dataset_bytes"] == dataset_bytes
        assert kwargs["dataset_id"] == dataset_id
        assert kwargs["slug"] == "candidate-1"
        registered_model_id = _create_model_with_bundle_artifact(
            slug=kwargs["slug"],
            bundle=b"bundle-bytes",
            dataset_id=kwargs["dataset_id"],
        )
        return _db.get(SemanticModel, registered_model_id)

    monkeypatch.setattr("ot_backend.semantic.train_worker.get_semantic_dataset_bytes", lambda _db, _dataset_id: dataset_bytes)
    monkeypatch.setattr("ot_backend.semantic.train_worker.default_eval_queries_bytes", lambda: eval_queries_bytes)
    monkeypatch.setattr("ot_backend.semantic.train_worker.modal_client_configured", lambda: True)
    monkeypatch.setattr(
        "ot_backend.semantic.train_worker._load_modal_train_module",
        lambda: _fake_modal_module(train=SimpleNamespace(remote=lambda *args: remote_calls.append(args) or b"bundle-bytes")),
    )
    monkeypatch.setattr("ot_backend.semantic.train_worker.register_model_bundle_bytes", fake_register_model_bundle_bytes)
    monkeypatch.setattr("ot_backend.semantic.train_worker.semantic_train_max_jobs_per_run", lambda: 5)

    exit_code = train_worker.main([])

    assert exit_code == 0
    assert remote_calls == [
        (
            dataset_bytes,
            eval_queries_bytes,
            "sentence-transformers/all-MiniLM-L6-v2",
            3,
            8,
            "none",
            False,
        )
    ]

    with SessionLocal() as db:
        job = db.get(SemanticJob, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.model_id == registered_model_id
        assert job.dataset_id == dataset_id
        assert job.heartbeat_at is not None
        assert job.result_json is not None
        assert job.result_json["model_id"] == registered_model_id
        assert job.result_json["model_slug"] == "candidate-1"
        assert job.result_json["dataset_id"] == dataset_id
        assert "bundle_zip" in job.result_json["artifact_keys"]


def test_train_worker_creates_follow_up_promote_job_when_requested(monkeypatch) -> None:
    _reset_tables()
    dataset_bytes = json.dumps({"version": 6, "metadata": {"semantic_data_version": 1}, "llm_query_examples": 0}).encode("utf-8")
    eval_queries_bytes = b'{"queries": []}'
    dataset_id = _create_dataset(slug="dataset-2", augmentation_mode="none", source_semantic_data_version=1)

    with SessionLocal() as db:
        job = create_train_job(
            db,
            requested_by="olmo",
            dataset_id=dataset_id,
            model_slug="candidate-2",
            base_model_key="mini-lm-l6-v2",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_dim=384,
            skip_fine_tune=False,
            epochs=2,
            batch_size=16,
            promote_after_register=True,
            embed_batch_size=256,
        )
        job_id = job.id

    def fake_register_model_bundle_bytes(_db, **kwargs):
        model_id = _create_model_with_bundle_artifact(
            slug=kwargs["slug"],
            bundle=b"bundle-bytes",
            dataset_id=kwargs["dataset_id"],
        )
        return _db.get(SemanticModel, model_id)

    monkeypatch.setattr("ot_backend.semantic.train_worker.get_semantic_dataset_bytes", lambda _db, _dataset_id: dataset_bytes)
    monkeypatch.setattr("ot_backend.semantic.train_worker.default_eval_queries_bytes", lambda: eval_queries_bytes)
    monkeypatch.setattr("ot_backend.semantic.train_worker.modal_client_configured", lambda: True)
    monkeypatch.setattr(
        "ot_backend.semantic.train_worker._load_modal_train_module",
        lambda: _fake_modal_module(train=SimpleNamespace(remote=lambda *_args: b"bundle-bytes")),
    )
    monkeypatch.setattr("ot_backend.semantic.train_worker.register_model_bundle_bytes", fake_register_model_bundle_bytes)

    exit_code = train_worker.main([])

    assert exit_code == 0

    with SessionLocal() as db:
        train_job = db.get(SemanticJob, job_id)
        assert train_job is not None
        assert train_job.status == "succeeded"
        assert train_job.result_json is not None
        promote_job_id = train_job.result_json["promote_job_id"]
        assert isinstance(promote_job_id, str)
        promote_job = db.get(SemanticJob, promote_job_id)
        assert promote_job is not None
        assert promote_job.job_type == "promote"
        assert promote_job.status == "pending"
        assert promote_job.requested_by == "olmo"


def test_train_worker_succeeds_when_follow_up_promote_enqueue_fails(monkeypatch) -> None:
    _reset_tables()
    dataset_bytes = json.dumps({"version": 6, "metadata": {"semantic_data_version": 1}, "llm_query_examples": 0}).encode("utf-8")
    eval_queries_bytes = b'{"queries": []}'
    dataset_id = _create_dataset(slug="dataset-3", augmentation_mode="none", source_semantic_data_version=1)
    registered_model_id: str | None = None

    with SessionLocal() as db:
        job = create_train_job(
            db,
            requested_by="olmo",
            dataset_id=dataset_id,
            model_slug="candidate-3",
            base_model_key="mini-lm-l6-v2",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_dim=384,
            skip_fine_tune=False,
            epochs=2,
            batch_size=16,
            promote_after_register=True,
            embed_batch_size=256,
        )
        job_id = job.id

    def fake_register_model_bundle_bytes(_db, **_kwargs):
        nonlocal registered_model_id
        registered_model_id = _create_model_with_bundle_artifact(
            slug="candidate-3",
            bundle=b"bundle-bytes",
            dataset_id=dataset_id,
        )
        return _db.get(SemanticModel, registered_model_id)

    monkeypatch.setattr("ot_backend.semantic.train_worker.get_semantic_dataset_bytes", lambda _db, _dataset_id: dataset_bytes)
    monkeypatch.setattr("ot_backend.semantic.train_worker.default_eval_queries_bytes", lambda: eval_queries_bytes)
    monkeypatch.setattr("ot_backend.semantic.train_worker.modal_client_configured", lambda: True)
    monkeypatch.setattr(
        "ot_backend.semantic.train_worker._load_modal_train_module",
        lambda: _fake_modal_module(train=SimpleNamespace(remote=lambda *_args: b"bundle-bytes")),
    )
    monkeypatch.setattr("ot_backend.semantic.train_worker.register_model_bundle_bytes", fake_register_model_bundle_bytes)
    monkeypatch.setattr(
        "ot_backend.semantic.train_worker.create_promote_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Another semantic promote job is already pending or running.")),
    )

    exit_code = train_worker.main([])

    assert exit_code == 0
    with SessionLocal() as db:
        train_job = db.get(SemanticJob, job_id)
        assert train_job is not None
        assert train_job.status == "succeeded"
        assert train_job.model_id == registered_model_id
        assert train_job.result_json is not None
        assert train_job.result_json["model_id"] == registered_model_id
        assert "promote_job_error" in train_job.result_json


def test_train_worker_runs_skip_fine_tune_locally(monkeypatch) -> None:
    _reset_tables()
    local_calls: list[tuple[object, ...]] = []
    dataset_bytes = json.dumps({"version": 6, "metadata": {"semantic_data_version": 4}, "llm_query_examples": 0}).encode("utf-8")
    eval_queries_bytes = b'{"queries": []}'
    dataset_id = _create_dataset(slug="dataset-skip", augmentation_mode="none", source_semantic_data_version=4)

    with SessionLocal() as db:
        job = create_train_job(
            db,
            requested_by="olmo",
            dataset_id=dataset_id,
            model_slug="candidate-skip",
            base_model_key="mini-lm-l6-v2",
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_dim=384,
            skip_fine_tune=True,
            epochs=1,
            batch_size=4,
            promote_after_register=False,
            embed_batch_size=128,
        )
        job_id = job.id

    registered_model_id: str | None = None

    def fake_register_model_bundle_bytes(_db, **_kwargs):
        nonlocal registered_model_id
        registered_model_id = _create_model_with_bundle_artifact(
            slug="candidate-skip",
            bundle=b"bundle-bytes",
            dataset_id=dataset_id,
        )
        return _db.get(SemanticModel, registered_model_id)

    def fake_modal_client_configured() -> bool:
        raise AssertionError("Modal must not be contacted when skip_fine_tune=True.")

    monkeypatch.setattr("ot_backend.semantic.train_worker.get_semantic_dataset_bytes", lambda _db, _dataset_id: dataset_bytes)
    monkeypatch.setattr("ot_backend.semantic.train_worker.default_eval_queries_bytes", lambda: eval_queries_bytes)
    monkeypatch.setattr("ot_backend.semantic.train_worker.modal_client_configured", fake_modal_client_configured)
    monkeypatch.setattr(
        "ot_backend.semantic.train_worker._load_modal_train_module",
        lambda: SimpleNamespace(
            train=SimpleNamespace(
                local=lambda *args: local_calls.append(args) or b"bundle-bytes",
                remote=lambda *_args: (_ for _ in ()).throw(AssertionError("should not run")),
            )
        ),
    )
    monkeypatch.setattr("ot_backend.semantic.train_worker.register_model_bundle_bytes", fake_register_model_bundle_bytes)

    exit_code = train_worker.main([])

    assert exit_code == 0
    assert local_calls == [
        (
            dataset_bytes,
            eval_queries_bytes,
            "sentence-transformers/all-MiniLM-L6-v2",
            1,
            4,
            "none",
            True,
        )
    ]
    with SessionLocal() as db:
        train_job = db.get(SemanticJob, job_id)
        assert train_job is not None
        assert train_job.status == "succeeded"
        assert train_job.result_json is not None
        assert train_job.result_json["skip_fine_tune"] is True


def test_run_modal_training_requires_modal_credentials(monkeypatch) -> None:
    monkeypatch.setattr("ot_backend.semantic.train_worker.modal_client_configured", lambda: False)
    monkeypatch.setattr(
        "ot_backend.semantic.train_worker._load_modal_train_module",
        lambda: _fake_modal_module(train=SimpleNamespace(remote=lambda *_args: (_ for _ in ()).throw(AssertionError("should not run")))),
    )

    try:
        train_worker._run_modal_training(
            dataset_bytes=b"{}",
            eval_queries_bytes=b'{"queries": []}',
            base_model="sentence-transformers/all-MiniLM-L6-v2",
            epochs=1,
            batch_size=4,
            augmentation_mode="none",
            skip_fine_tune=False,
        )
    except RuntimeError as exc:
        assert "Modal client credentials" in str(exc)
    else:
        raise AssertionError("Expected Modal credentials validation to fail.")


def test_train_worker_marks_stale_running_jobs_failed() -> None:
    _reset_tables()
    stale_started_at = _utcnow_naive() - timedelta(minutes=25)

    with SessionLocal() as db:
        job = SemanticJob(
            job_type="train",
            status="running",
            requested_by="olmo",
            payload_json={"model_slug": "candidate-1"},
            started_at=stale_started_at,
            heartbeat_at=stale_started_at,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    exit_code = train_worker.main([])

    assert exit_code == 1
    with SessionLocal() as db:
        job = db.get(SemanticJob, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.finished_at is not None
        assert "heartbeat went stale" in (job.error_message or "")


def test_create_train_job_records_base_model_key_and_embedding_dim() -> None:
    _reset_tables()
    dataset_id = _create_dataset(slug="dataset-payload")

    with SessionLocal() as db:
        job = create_train_job(
            db,
            requested_by="olmo",
            dataset_id=dataset_id,
            model_slug="candidate-payload",
            base_model_key="mini-lm-l6-v2",
            base_model=get_semantic_base_model("mini-lm-l6-v2").base_model,
            embedding_dim=get_semantic_base_model("mini-lm-l6-v2").embedding_dim,
            skip_fine_tune=True,
            epochs=1,
            batch_size=4,
            promote_after_register=False,
            embed_batch_size=128,
        )

    assert job.payload_json["dataset_id"] == dataset_id
    assert job.payload_json["base_model_key"] == "mini-lm-l6-v2"
    assert job.payload_json["embedding_dim"] == 384


def test_mark_semantic_job_failed_rejects_terminal_job() -> None:
    _reset_tables()

    with SessionLocal() as db:
        job = SemanticJob(
            job_type="train",
            status="succeeded",
            requested_by="olmo",
            payload_json={"model_slug": "candidate-1"},
            finished_at=_utcnow_naive(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    try:
        mark_semantic_job_failed(job_id, error_message="late failure")
    except RuntimeError as exc:
        assert "is not running" in str(exc)
    else:
        raise AssertionError("Expected mark_semantic_job_failed to reject terminal job.")


def test_fail_stale_promote_job_releases_embedding_model_lock() -> None:
    _reset_tables()

    stale_at = _utcnow_naive() - timedelta(minutes=5)
    dataset_id = _create_dataset(slug="dataset-promote")

    stale_model_id = _create_model_with_bundle_artifact(
        slug="stale-promote-model",
        bundle=b"stale-bundle",
        status="embedding",
        dataset_id=dataset_id,
    )
    next_model_id = _create_model_with_bundle_artifact(
        slug="next-promote-model",
        bundle=b"next-bundle",
        dataset_id=dataset_id,
    )

    with SessionLocal() as db:
        stale_job = SemanticJob(
            job_type="promote",
            status="running",
            requested_by="olmo",
            model_id=stale_model_id,
            payload_json={"model_id": stale_model_id, "embed_batch_size": 128},
            started_at=stale_at,
            heartbeat_at=stale_at,
        )
        db.add(stale_job)
        db.commit()
        db.refresh(stale_job)
        stale_job_id = stale_job.id

    stale_job_ids = fail_stale_running_jobs(job_type="promote", stale_after_seconds=60)

    assert stale_job_ids == [stale_job_id]
    del next_model_id  # a fresh promotion is no longer tested here — the stale-cleanup invariant is what matters

    with SessionLocal() as db:
        stale_job = db.get(SemanticJob, stale_job_id)
        stale_model = db.get(SemanticModel, stale_model_id)

        assert stale_job is not None
        assert stale_job.status == "failed"
        assert "heartbeat went stale" in (stale_job.error_message or "")

        assert stale_model is not None
        assert stale_model.status == "failed"
        assert stale_model.is_active is False
        assert "heartbeat went stale" in (stale_model.error_message or "")


def test_train_worker_marks_job_failed_for_invalid_payload() -> None:
    _reset_tables()

    with SessionLocal() as db:
        job = SemanticJob(
            job_type="train",
            status="pending",
            requested_by="olmo",
            payload_json={"base_model": "sentence-transformers/all-MiniLM-L6-v2"},
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    exit_code = train_worker.main([])

    assert exit_code == 1
    with SessionLocal() as db:
        job = db.get(SemanticJob, job_id)
        assert job is not None
        assert job.status == "failed"
        assert "dataset_id" in (job.error_message or "")


def test_promotion_worker_runs_pending_promote_job(monkeypatch) -> None:
    _reset_tables()

    dataset_id = _create_dataset(slug="dataset-promote-ready")
    model_id = _create_model_with_bundle_artifact(
        slug="candidate-promote",
        bundle=b"promote-bundle",
        dataset_id=dataset_id,
    )

    with SessionLocal() as db:
        job = create_promote_job(db, requested_by="olmo", model_id=model_id, embed_batch_size=128)
        job_id = job.id

    monkeypatch.setattr(
        "ot_backend.semantic.promote_worker.promote_semantic_model",
        lambda model_id, *, embed_batch_size: isinstance(model_id, str) and len(model_id) > 0 and embed_batch_size == 128,
    )

    exit_code = promote_worker.main([])

    assert exit_code == 0
    with SessionLocal() as db:
        job = db.get(SemanticJob, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.heartbeat_at is not None
        assert job.result_json == {"model_id": model_id, "final_status": "active"}


def test_create_promote_job_rejects_second_pending_or_running_job() -> None:
    _reset_tables()

    dataset_id = _create_dataset(slug="dataset-promote-lock")
    first_model_id = _create_model_with_bundle_artifact(slug="candidate-a", bundle=b"bundle-a", dataset_id=dataset_id)
    second_model_id = _create_model_with_bundle_artifact(slug="candidate-b", bundle=b"bundle-b", dataset_id=dataset_id)

    with SessionLocal() as db:
        create_promote_job(db, requested_by="olmo", model_id=first_model_id, embed_batch_size=128)

        try:
            create_promote_job(db, requested_by="olmo", model_id=second_model_id, embed_batch_size=128)
        except RuntimeError as exc:
            assert "already pending or running" in str(exc)
        else:
            raise AssertionError("Expected second promote job creation to fail.")
