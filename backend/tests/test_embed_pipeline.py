from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import init_db
from ot_backend.core.models import (
    Card,
    CardFace,
    CardRaw,
    CardTagging,
    SemanticJob,
    SemanticModel,
    SemanticModelArtifact,
    SystemMetadata,
    Tag,
)
from ot_backend.embed import pipeline as pipeline_module
from ot_backend.embed.pipeline import (
    LazyInputExampleDataset,
    PipelineConfig,
    _make_run_id,
    build_training_dataset_state,
    export_onnx_model,
    export_training_dataset,
    load_training_dataset,
    main,
)
from ot_backend.embed.semantic_state import bump_semantic_data_version, get_exported_dataset_version
from ot_backend.embed.text_prep import face_to_text
from ot_backend.embed.train_options import DEFAULT_TRAIN_AUGMENTATION_KEYS, TRAIN_AUGMENTATION_LLM_QUERIES


@dataclass
class DummyInputExample:
    texts: list[str]


# ---------------------------------------------------------------------------
# Fixtures / seed helpers
# ---------------------------------------------------------------------------


def _reset_tables() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(SemanticJob).delete()
        db.query(SemanticModelArtifact).delete()
        db.query(SemanticModel).delete()
        db.query(CardTagging).delete()
        db.query(Tag).delete()
        db.query(CardFace).delete()
        db.query(Card).delete()
        db.query(CardRaw).delete()
        db.query(SystemMetadata).filter(SystemMetadata.key.in_(["semantic_data", "semantic_dataset_export", "semantic_active_model"])).delete()
        db.commit()


def _make_card_raw(*, scryfall_id: str, oracle_id: str, name: str, collector_number: str) -> CardRaw:
    return CardRaw(
        id=scryfall_id,
        oracle_id=oracle_id,
        name=name,
        lang="en",
        layout="normal",
        color_identity=[],
        keywords=[],
        legalities={},
        rarity="common",
        set_code="tst",
        set_id="set-tst",
        set_name="Test Set",
        set_type="expansion",
        collector_number=collector_number,
        games=["paper"],
        finishes=["nonfoil"],
    )


def _seed_records() -> None:
    _reset_tables()
    with SessionLocal() as db:
        db.add_all(
            [
                _make_card_raw(scryfall_id="scryfall-1", oracle_id="oracle-1", name="Shock", collector_number="1"),
                _make_card_raw(scryfall_id="scryfall-2", oracle_id="oracle-2", name="Lightning Bolt", collector_number="2"),
                _make_card_raw(scryfall_id="scryfall-3", oracle_id="oracle-3", name="Llanowar Elves", collector_number="3"),
                Card(oracle_id="oracle-1", scryfall_id="scryfall-1", name="Shock", layout="normal", rarity="common", legalities={}, color_identity=["R"]),
                Card(
                    oracle_id="oracle-2",
                    scryfall_id="scryfall-2",
                    name="Lightning Bolt",
                    layout="normal",
                    rarity="common",
                    legalities={},
                    color_identity=["R"],
                ),
                Card(
                    oracle_id="oracle-3",
                    scryfall_id="scryfall-3",
                    name="Llanowar Elves",
                    layout="normal",
                    rarity="common",
                    legalities={},
                    color_identity=["G"],
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                CardFace(
                    oracle_id="oracle-1",
                    face_ix=0,
                    name="Shock",
                    type_line="Instant",
                    oracle_text="Shock deals 2 damage to any target.",
                    colors=["R"],
                ),
                CardFace(
                    oracle_id="oracle-2",
                    face_ix=0,
                    name="Lightning Bolt",
                    type_line="Instant",
                    oracle_text="Lightning Bolt deals 3 damage to any target.",
                    colors=["R"],
                ),
                CardFace(
                    oracle_id="oracle-3",
                    face_ix=0,
                    name="Llanowar Elves",
                    type_line="Creature — Elf Druid",
                    oracle_text="{T}: Add {G}.",
                    colors=["G"],
                ),
            ]
        )
        db.flush()
        db.add(Tag(id="tag-1", tag_name="burn", tag_namespace="card"))
        db.flush()
        db.add_all(
            [
                CardTagging(id="tagging-1", card_id="oracle-1", tag_id="tag-1", foreign_key="oracleId"),
                CardTagging(id="tagging-2", card_id="oracle-2", tag_id="tag-1", foreign_key="oracleId"),
            ]
        )
        db.commit()


# ---------------------------------------------------------------------------
# PipelineConfig serialization
# ---------------------------------------------------------------------------


def test_pipeline_config_round_trips_json(tmp_path: Path) -> None:
    config = PipelineConfig(epochs=3, batch_size=16, run_name="test")
    json_str = config.to_json()
    parsed = json.loads(json_str)

    assert parsed["epochs"] == 3
    assert parsed["batch_size"] == 16
    assert parsed["run_name"] == "test"


def test_pipeline_config_from_json_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"epochs": 2, "batch_size": 4}), encoding="utf-8")

    config = PipelineConfig.from_json_file(config_file)

    assert config.epochs == 2
    assert config.batch_size == 4
    assert config.base_model == PipelineConfig().base_model


def test_pipeline_config_json_file_loaded_via_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"epochs": 7}), encoding="utf-8")

    runs: list[PipelineConfig] = []
    monkeypatch.setattr("ot_backend.embed.pipeline.run_pipeline", lambda cfg, run_dir: runs.append(cfg) or 0)
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-id")

    main(["run", "--config", str(config_file), "--runs-dir", str(tmp_path)])

    assert runs[0].epochs == 7


# ---------------------------------------------------------------------------
# Dataset building
# ---------------------------------------------------------------------------


def test_build_dataset_uses_face_ids_and_lazy_text_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_records()
    monkeypatch.setattr("ot_backend.embed.dataset_service.random.shuffle", lambda seq: None)

    with SessionLocal() as db:
        state = build_training_dataset_state(db, max_tag_pair_group_size=2)
        face_rows = db.query(CardFace).order_by(CardFace.oracle_id, CardFace.face_ix).all()

    assert len(state.face_texts) == 3
    assert state.simcse_examples == 3
    assert state.tag_pair_examples == 1
    assert len(state.pair_ids) == 4

    dataset = LazyInputExampleDataset(state.pair_ids, state.face_texts, DummyInputExample)
    self_pair = dataset[0]
    tag_pair = dataset[-1]

    assert self_pair.texts[0] == self_pair.texts[1]
    assert self_pair.texts[0] == face_to_text(face_rows[0])
    assert tag_pair.texts == [face_to_text(face_rows[0]), face_to_text(face_rows[1])]


def test_build_dataset_ignores_non_card_or_non_oracle_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_records()
    monkeypatch.setattr("ot_backend.embed.dataset_service.random.shuffle", lambda seq: None)

    with SessionLocal() as db:
        db.add_all(
            [
                Tag(id="tag-2", tag_name="foil", tag_namespace="artwork"),
                Tag(id="tag-3", tag_name="tribal", tag_namespace="card"),
            ]
        )
        db.add_all(
            [
                CardTagging(id="tagging-3", card_id="oracle-1", tag_id="tag-2", foreign_key="oracleId"),
                CardTagging(id="tagging-4", card_id="oracle-2", tag_id="tag-3", foreign_key="illustrationId"),
            ]
        )
        db.commit()
        state = build_training_dataset_state(db, max_tag_pair_group_size=2)

    assert state.tag_pair_examples == 1


def test_build_dataset_can_disable_optional_augmentations(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_records()
    monkeypatch.setattr("ot_backend.embed.dataset_service.random.shuffle", lambda seq: None)

    with SessionLocal() as db:
        state = build_training_dataset_state(
            db,
            augmentation_mode="none",
            max_tag_pair_group_size=2,
        )

    assert state.simcse_examples == 3
    assert state.tag_pair_examples == 0
    assert state.tag_desc_pair_examples == 0
    assert state.template_query_examples == 0
    assert len(state.pair_ids) == 3
    assert state.direct_text_pairs == []


def test_default_augmentation_mode_keeps_llm_queries_opt_in() -> None:
    assert TRAIN_AUGMENTATION_LLM_QUERIES not in DEFAULT_TRAIN_AUGMENTATION_KEYS


def test_export_and_load_training_dataset_round_trips(tmp_path: Path) -> None:
    _seed_records()

    with SessionLocal() as db:
        state = build_training_dataset_state(db)

    export_path = tmp_path / "dataset.json"
    export_training_dataset(state, export_path)
    loaded = load_training_dataset(export_path)

    assert loaded == state


def test_export_dataset_command_records_semantic_version(tmp_path: Path) -> None:
    _seed_records()
    export_path = tmp_path / "dataset.json"

    with SessionLocal() as db:
        bump_semantic_data_version(db)

    main(["export", str(export_path)])

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["semantic_data_version"] == 1

    with SessionLocal() as db:
        assert get_exported_dataset_version(db) == 1


def test_register_model_command_uses_dataset_metadata(monkeypatch, tmp_path: Path) -> None:
    _seed_records()
    monkeypatch.setattr("ot_backend.embed.artifacts.upload_artifact_bytes", lambda **_kwargs: None)
    bundle_root = tmp_path / "bundle"
    (bundle_root / "models" / "onnx" / "onnx").mkdir(parents=True)
    (bundle_root / "models" / "onnx" / "onnx" / "model.onnx").write_bytes(b"onnx")
    (bundle_root / "models" / "onnx" / "tokenizer.json").write_text("{}", encoding="utf-8")
    (bundle_root / "models" / "onnx" / "1_Pooling").mkdir(parents=True)
    (bundle_root / "models" / "onnx" / "1_Pooling" / "config.json").write_text(
        '{"pooling_mode_mean_tokens": true}',
        encoding="utf-8",
    )
    (bundle_root / "models" / "pytorch").mkdir(parents=True)
    (bundle_root / "models" / "pytorch" / "config.json").write_text("{}", encoding="utf-8")
    (bundle_root / "embeddings").mkdir(parents=True)
    np.savez_compressed(
        bundle_root / "embeddings" / "embeddings.npz",
        oracle_ids=np.asarray(["o1"]),
        face_ixs=np.asarray([0], dtype=np.int32),
        embeddings=np.asarray([[1.0] + [0.0] * 383], dtype=np.float32),
    )
    (bundle_root / "training").mkdir(parents=True)
    (bundle_root / "training" / "training-dataset.json").write_text(
        '{"version": 5, "face_texts": [], "pair_ids": [], "direct_text_pairs": [], "simcse_examples": 0, "tag_pair_examples": 0, "tag_desc_pair_examples": 0, "template_query_examples": 0, "metadata": {"semantic_data_version": 7}}',
        encoding="utf-8",
    )
    (bundle_root / "eval").mkdir(parents=True)
    (bundle_root / "eval" / "eval.json").write_text(
        '{"version": 1, "summary": {"query_count": 1, "top1_hits": 1, "top3_hits": 1, "top5_hits": 1, "top1_rate": 1.0, "top3_rate": 1.0, "top5_rate": 1.0, "mrr": 1.0}, "queries": []}',
        encoding="utf-8",
    )
    (bundle_root / "config.json").write_text(json.dumps({"epochs": 2}), encoding="utf-8")
    (bundle_root / "metrics.json").write_text(json.dumps({"loss": 0.1}), encoding="utf-8")
    (bundle_root / "manifest.json").write_text(
        '{"version": 1, "bundle": {"has_onnx_model": true, "has_pytorch_model": true, "has_precomputed_embeddings": true, "has_training_dataset": true, "has_eval_json": true}, "source_semantic_data_version": 7, "dataset_metadata": {"semantic_data_version": 7}}',
        encoding="utf-8",
    )

    exit_code = main(
        [
            "register",
            str(bundle_root),
            "--model-slug",
            "candidate-model",
            "--base-model",
            "sentence-transformers/all-MiniLM-L6-v2",
            "--augmentation-mode",
            "none",
        ]
    )

    assert exit_code == 0
    with SessionLocal() as db:
        model = db.query(SemanticModel).order_by(SemanticModel.id.desc()).first()

    assert model is not None
    assert model.slug == "candidate-model"
    assert model.config_json is not None
    assert model.config_json["semantic_data_version"] == 7
    assert model.config_json["dataset_metadata"] == {"semantic_data_version": 7}
    with SessionLocal() as db:
        artifacts = db.query(SemanticModelArtifact).filter(SemanticModelArtifact.model_id == model.id).all()
    assert {artifact.artifact_kind for artifact in artifacts} == {"bundle_zip", "training_dataset", "eval_json", "manifest_json"}


# ---------------------------------------------------------------------------
# Pipeline: --no-fine-tune
# ---------------------------------------------------------------------------


def test_pipeline_no_fine_tune_exports_base_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exported: list[tuple[str, Path]] = []
    saved_paths: list[str] = []

    class FakeModel:
        def __init__(self, model_name: str) -> None:
            self.base_model_name = model_name

        def save(self, path: str) -> None:
            saved_paths.append(path)

    monkeypatch.setattr(
        "ot_backend.embed.pipeline.export_onnx_model",
        lambda src, out: exported.append((src, out)),
    )
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256, output_path=None: 0,
    )
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._load_sentence_transformer_class",
        lambda: (lambda model_name: FakeModel(model_name)),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["run", "--no-fine-tune", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert len(exported) == 1
    assert len(saved_paths) == 1
    assert saved_paths[0].endswith("models/pytorch")
    assert exported[0][0].endswith("models/pytorch")


# ---------------------------------------------------------------------------
# Pipeline: full run (fine-tune → embeddings → save → onnx export)
# ---------------------------------------------------------------------------


def test_pipeline_default_fine_tunes_then_computes_embeddings_then_exports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "ot_backend.embed.pipeline._prepare_and_save_dataset",
        lambda path, config: (
            calls.append(f"prepare:{path}"),
            path.parent.mkdir(parents=True, exist_ok=True),
            path.write_text(
                '{"version":5,"face_texts":[],"pair_ids":[],"direct_text_pairs":[],"simcse_examples":0,"tag_pair_examples":0,"tag_desc_pair_examples":0,"template_query_examples":0,"metadata":{"semantic_data_version":1}}',
                encoding="utf-8",
            ),
        )[-1],
    )

    class FakeModel:
        def __init__(self, name: str) -> None:
            self.name = name
            self.saved_path: str | None = None

        def save(self, path: str) -> None:
            self.saved_path = path

    fake_model = FakeModel("base")

    monkeypatch.setattr(
        "ot_backend.embed.pipeline._train",
        lambda config, state, run_dir: calls.append("train") or fake_model,
    )
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256, output_path=None: calls.append(f"embed:{output_path}") or 3,
    )
    monkeypatch.setattr(
        "ot_backend.embed.pipeline.export_onnx_model",
        lambda src, out: calls.append(f"onnx:{src}"),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["run", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert "train" in calls
    assert any(call.startswith("embed:") for call in calls)
    assert any(c.startswith("onnx:") for c in calls)

    # ONNX export receives the saved PyTorch path, not the base model name
    onnx_call = next(c for c in calls if c.startswith("onnx:"))
    assert "pytorch" in onnx_call
    embed_call = next(c for c in calls if c.startswith("embed:"))
    assert "embeddings/embeddings.npz" in embed_call

    # Verify run dir artifacts
    run_dir = tmp_path / "test-run"
    assert (run_dir / "config.json").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "training" / "training-dataset.json").exists()
    assert not (tmp_path / "latest").exists()


# ---------------------------------------------------------------------------
# Pipeline: DB session is closed before model.fit()
# ---------------------------------------------------------------------------


def test_pipeline_closes_db_session_before_training(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_records()

    class RecordingSession:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.closed = False

        def execute(self, *args: Any, **kwargs: Any) -> Any:
            return self._inner.execute(*args, **kwargs)

        def close(self) -> None:
            self.closed = True
            self._inner.close()

    real_session = SessionLocal()
    recording = RecordingSession(real_session)

    call_count = [0]

    def fake_session_local() -> Any:
        call_count[0] += 1
        if call_count[0] == 1:
            return recording
        return SessionLocal()

    class FakeDataLoader:
        def __init__(self, dataset: Any, shuffle: bool, batch_size: int) -> None:
            self.dataset = dataset
            self.batch_size = batch_size

        def __len__(self) -> int:
            return len(self.dataset)

    class FakeLosses:
        @staticmethod
        def MultipleNegativesRankingLoss(model: Any) -> str:
            return f"loss-for-{model.base_model_name}"

    class FakeSentenceTransformer:
        instances: list["FakeSentenceTransformer"] = []

        def __init__(self, base_model_name: str) -> None:
            self.base_model_name = base_model_name
            self.fit_calls: list[dict[str, Any]] = []
            self.saved_path: str | None = None
            self.session_closed_at_fit = False
            FakeSentenceTransformer.instances.append(self)

        def fit(self, **kwargs: Any) -> None:
            self.fit_calls.append(kwargs)
            self.session_closed_at_fit = recording.closed

        def save(self, path: str) -> None:
            self.saved_path = path

    FakeSentenceTransformer.instances = []

    def fake_import_module(name: str) -> Any:
        if name == "torch.utils.data":
            return SimpleNamespace(DataLoader=FakeDataLoader)
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr("ot_backend.embed.dataset_service.SessionLocal", fake_session_local)
    monkeypatch.setattr("ot_backend.embed.training_service._ensure_training_dependencies", lambda: None)
    monkeypatch.setattr(
        "ot_backend.embed.training_service._load_sentence_transformers",
        lambda: (FakeSentenceTransformer, DummyInputExample, FakeLosses),
    )
    monkeypatch.setattr("ot_backend.embed.training_service.huggingface_cache_dir", lambda: tmp_path / "hf")
    monkeypatch.setattr("ot_backend.embed.training_service.import_module", fake_import_module)
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256, output_path=None: 0,
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["run", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert recording.closed is True
    assert len(FakeSentenceTransformer.instances) == 1
    model = FakeSentenceTransformer.instances[0]
    assert model.session_closed_at_fit is True


# ---------------------------------------------------------------------------
# Pipeline: train from pre-exported dataset (Colab / offline workflow)
# ---------------------------------------------------------------------------


def test_pipeline_can_train_from_pre_exported_dataset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_records()

    with SessionLocal() as db:
        state = build_training_dataset_state(db)

    dataset_path = tmp_path / "dataset.json"
    export_training_dataset(state, dataset_path)

    class FakeDataLoader:
        def __init__(self, dataset: Any, shuffle: bool, batch_size: int) -> None:
            self.dataset = dataset

    class FakeLosses:
        @staticmethod
        def MultipleNegativesRankingLoss(model: Any) -> str:
            return "loss"

    class FakeSentenceTransformer:
        instances: list["FakeSentenceTransformer"] = []

        def __init__(self, name: str) -> None:
            self.name = name
            self.fit_calls: list[Any] = []
            self.saved_path: str | None = None
            FakeSentenceTransformer.instances.append(self)

        def fit(self, **kwargs: Any) -> None:
            self.fit_calls.append(kwargs)

        def save(self, path: str) -> None:
            self.saved_path = path

    FakeSentenceTransformer.instances = []

    monkeypatch.setattr(
        "ot_backend.embed.dataset_service.SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("DB must not be used")),
    )
    monkeypatch.setattr("ot_backend.embed.training_service._ensure_training_dependencies", lambda: None)
    monkeypatch.setattr(
        "ot_backend.embed.training_service._load_sentence_transformers",
        lambda: (FakeSentenceTransformer, DummyInputExample, FakeLosses),
    )
    monkeypatch.setattr("ot_backend.embed.training_service.huggingface_cache_dir", lambda: tmp_path / "hf")

    def fake_import_module(name: str) -> Any:
        if name == "torch.utils.data":
            return SimpleNamespace(DataLoader=FakeDataLoader)
        raise AssertionError(f"Unexpected: {name}")

    monkeypatch.setattr("ot_backend.embed.training_service.import_module", fake_import_module)
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256, output_path=None: 0,
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["run", "--dataset-path", str(dataset_path), "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert len(FakeSentenceTransformer.instances) == 1


# ---------------------------------------------------------------------------
# Pipeline: MPS fallback
# ---------------------------------------------------------------------------


def test_pipeline_uses_old_fit_on_mps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _seed_records()

    class FakeDataLoader:
        def __init__(self, dataset: Any, shuffle: bool, batch_size: int) -> None:
            self.dataset = dataset

        def __len__(self) -> int:
            return len(self.dataset)

    class FakeLosses:
        @staticmethod
        def MultipleNegativesRankingLoss(model: Any) -> str:
            return "loss"

    class FakeSentenceTransformer:
        instances: list["FakeSentenceTransformer"] = []

        def __init__(self, name: str) -> None:
            self.name = name
            self.fit_calls: list[Any] = []
            self.old_fit_calls: list[Any] = []
            self.saved_path: str | None = None
            FakeSentenceTransformer.instances.append(self)

        def fit(self, **kwargs: Any) -> None:
            self.fit_calls.append(kwargs)

        def old_fit(self, **kwargs: Any) -> None:
            self.old_fit_calls.append(kwargs)

        def save(self, path: str) -> None:
            self.saved_path = path

    FakeSentenceTransformer.instances = []

    monkeypatch.setattr("ot_backend.embed.training_service._ensure_training_dependencies", lambda: None)
    monkeypatch.setattr(
        "ot_backend.embed.training_service._load_sentence_transformers",
        lambda: (FakeSentenceTransformer, DummyInputExample, FakeLosses),
    )
    monkeypatch.setattr("ot_backend.embed.training_service.huggingface_cache_dir", lambda: tmp_path / "hf")
    monkeypatch.setattr("ot_backend.embed.training_service._is_mps_available", lambda: True)
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256, output_path=None: 0,
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    def fake_import_module(name: str) -> Any:
        if name == "torch.utils.data":
            return SimpleNamespace(DataLoader=FakeDataLoader)
        raise AssertionError(f"Unexpected: {name}")

    monkeypatch.setattr("ot_backend.embed.training_service.import_module", fake_import_module)

    exit_code = main(["run", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    model = FakeSentenceTransformer.instances[0]
    assert len(model.old_fit_calls) == 1
    assert model.fit_calls == []


# ---------------------------------------------------------------------------
# ONNX export
# ---------------------------------------------------------------------------


def test_export_onnx_model_writes_conventional_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, object], bool]] = []

    class FakeSentenceTransformer:
        def __init__(self, model_source: str, **kwargs: object) -> None:
            calls.append((model_source, kwargs, False))

        def save(self, path: str) -> None:
            model_path, kwargs, _ = calls[-1]
            calls[-1] = (model_path, kwargs, True)
            assert path == str(tmp_path / "out")

    monkeypatch.setattr(
        "ot_backend.embed.training_service._load_sentence_transformer_class", lambda: FakeSentenceTransformer
    )
    monkeypatch.setattr("ot_backend.embed.training_service.huggingface_cache_dir", lambda: tmp_path / "hf")

    export_onnx_model("sentence-transformers/test-model", tmp_path / "out")

    assert calls == [
        (
            "sentence-transformers/test-model",
            {
                "backend": "onnx",
                "model_kwargs": {
                    "provider": "CPUExecutionProvider",
                    "export": True,
                    "file_name": "onnx/model.onnx",
                },
                "local_files_only": False,
            },
            True,
        )
    ]


# ---------------------------------------------------------------------------
# Run versioning
# ---------------------------------------------------------------------------


def test_make_run_id_includes_timestamp() -> None:
    run_id = _make_run_id()
    assert len(run_id) == 15  # YYYYMMDD-HHMMSS
    assert run_id[8] == "-"


def test_make_run_id_appends_run_name() -> None:
    run_id = _make_run_id("larger-batch")
    assert run_id.endswith("-larger-batch")


def test_pipeline_creates_bundle_shaped_versioned_run_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "20260324-120000")
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256, output_path=None: 0,
    )
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._prepare_and_save_dataset",
        lambda path, config: (
            path.parent.mkdir(parents=True, exist_ok=True),
            path.write_text(
                '{"version":5,"face_texts":[],"pair_ids":[],"direct_text_pairs":[],"simcse_examples":0,"tag_pair_examples":0,"tag_desc_pair_examples":0,"template_query_examples":0}',
                encoding="utf-8",
            ),
        )[-1],
    )

    class FakeModel:
        def save(self, path: str) -> None:
            pass

    monkeypatch.setattr(
        "ot_backend.embed.pipeline._train",
        lambda config, state, run_dir: FakeModel(),
    )

    exit_code = main(["run", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    run_dir = tmp_path / "20260324-120000"
    assert run_dir.is_dir()
    assert (run_dir / "config.json").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "training" / "training-dataset.json").exists()
    assert (run_dir / "manifest.json").exists()
    assert not (tmp_path / "latest").exists()


# ---------------------------------------------------------------------------
# --no-embeddings flag
# ---------------------------------------------------------------------------


def test_pipeline_no_embeddings_skips_compute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    compute_calls: list[Any] = []
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256, output_path=None: compute_calls.append(model) or 0,
    )
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._prepare_and_save_dataset",
        lambda path, config: (
            path.parent.mkdir(parents=True, exist_ok=True),
            path.write_text(
                '{"version":5,"face_texts":[],"pair_ids":[],"direct_text_pairs":[],"simcse_examples":0,"tag_pair_examples":0,"tag_desc_pair_examples":0,"template_query_examples":0}',
                encoding="utf-8",
            ),
        )[-1],
    )

    class FakeModel:
        def save(self, path: str) -> None:
            pass

    monkeypatch.setattr(
        "ot_backend.embed.pipeline._train",
        lambda config, state, run_dir: FakeModel(),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["run", "--no-embeddings", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert compute_calls == []


# ---------------------------------------------------------------------------
# --reembed-only
# ---------------------------------------------------------------------------


def test_reembed_only_loads_model_and_reembeds_without_touching_run_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_dir = tmp_path / "my-run" / "pytorch"
    model_dir.mkdir(parents=True)

    loaded: list[str] = []
    embedded: list[Any] = []

    monkeypatch.setattr(
        "ot_backend.embed.pipeline._load_sentence_transformer_class",
        lambda: (lambda path: loaded.append(path) or object()),
    )
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256, output_path=None: embedded.append(model) or 5,
    )

    exit_code = main(["reembed", "--base-model", str(model_dir), "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert loaded == [str(model_dir)]
    assert len(embedded) == 1
    # No run dirs or latest symlink created
    assert not (tmp_path / "latest").exists()
    assert not any((tmp_path / d).is_dir() for d in ["pytorch", "onnx"])


def test_reembed_only_uses_base_model_from_config_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_dir = tmp_path / "explicit-model"
    model_dir.mkdir(parents=True)
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"base_model": str(model_dir)}), encoding="utf-8")

    loaded: list[str] = []
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._load_sentence_transformer_class",
        lambda: (lambda path: loaded.append(path) or object()),
    )
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256, output_path=None: 0,
    )

    exit_code = main(["reembed", "--config", str(config_file), "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert loaded == [str(model_dir)]


# ---------------------------------------------------------------------------
# Eval dataset lookup
# ---------------------------------------------------------------------------


def _write_eval_fixture_files(run_dir: Path, eval_path: Path) -> None:
    embeddings_dir = run_dir / "embeddings"
    embeddings_dir.mkdir(parents=True)
    np.savez_compressed(
        embeddings_dir / "embeddings.npz",
        oracle_ids=np.array(["oracle-1"]),
        face_ixs=np.array([0], dtype=np.int32),
        embeddings=np.array([[1.0, 0.0]], dtype=np.float32),
    )
    eval_path.write_text(json.dumps({"queries": [{"query": "burn spell"}]}), encoding="utf-8")


def _write_training_dataset_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 4,
                "face_texts": [
                    {"oracle_id": "oracle-1", "face_ix": 0, "text": "this card deals three damage to any target."}
                ],
                "pair_ids": [],
                "direct_text_pairs": [],
                "simcse_examples": 0,
                "tag_pair_examples": 0,
                "tag_desc_pair_examples": 0,
                "template_query_examples": 0,
            }
        ),
        encoding="utf-8",
    )


def test_run_eval_uses_dataset_from_explicit_run_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "semantic" / "runs" / "20260414-120000"
    eval_path = tmp_path / "eval.json"
    _write_eval_fixture_files(run_dir, eval_path)
    _write_training_dataset_fixture(run_dir / "training" / "training-dataset.json")

    class FakeSentenceTransformer:
        def __init__(self, model_source: str) -> None:
            self.model_source = model_source

        def encode(self, texts: list[str], normalize_embeddings: bool, show_progress_bar: bool) -> np.ndarray:
            assert texts == ["burn spell"]
            assert normalize_embeddings is True
            assert show_progress_bar is False
            return np.array([[1.0, 0.0]], dtype=np.float32)

    monkeypatch.setattr("ot_backend.embed.pipeline._load_sentence_transformer_class", lambda: FakeSentenceTransformer)

    assert pipeline_module._run_eval(run_dir=run_dir, model_source=None, eval_path=eval_path) == 0


def test_run_eval_uses_packaged_queries_when_eval_path_is_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "semantic" / "runs" / "20260414-120000"
    _write_eval_fixture_files(run_dir, tmp_path / "ignored.json")
    _write_training_dataset_fixture(run_dir / "training" / "training-dataset.json")

    class FakeSentenceTransformer:
        def __init__(self, model_source: str) -> None:
            self.model_source = model_source

        def encode(self, texts: list[str], normalize_embeddings: bool, show_progress_bar: bool) -> np.ndarray:
            return np.array([[1.0, 0.0]], dtype=np.float32)

    monkeypatch.setattr("ot_backend.embed.pipeline._load_sentence_transformer_class", lambda: FakeSentenceTransformer)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline.load_eval_queries_payload",
        lambda _payload=None: {"queries": [{"query": "burn spell"}]},
    )

    assert pipeline_module._run_eval(run_dir=run_dir, model_source=None, eval_path=None) == 0


def test_run_eval_raises_actionable_error_when_dataset_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "semantic" / "runs" / "20260414-120000"
    eval_path = tmp_path / "eval.json"
    _write_eval_fixture_files(run_dir, eval_path)

    with pytest.raises(FileNotFoundError) as excinfo:
        pipeline_module._run_eval(run_dir=run_dir, model_source=None, eval_path=eval_path)

    message = str(excinfo.value)
    assert str(run_dir / "training" / "training-dataset.json") in message
