from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import init_db
from ot_backend.core.models import Card, CardFace, CardTagging, Tag
from ot_backend.embed.pipeline import (
    LazyInputExampleDataset,
    PipelineConfig,
    TrainingDatasetState,
    _make_run_id,
    build_training_dataset_state,
    export_onnx_model,
    export_training_dataset,
    load_training_dataset,
    main,
)
from ot_backend.embed.text_prep import face_to_text


@dataclass
class DummyInputExample:
    texts: list[str]


# ---------------------------------------------------------------------------
# Fixtures / seed helpers
# ---------------------------------------------------------------------------


def _reset_tables() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(CardTagging).delete()
        db.query(Tag).delete()
        db.query(CardFace).delete()
        db.query(Card).delete()
        db.commit()


def _seed_records() -> None:
    _reset_tables()
    with SessionLocal() as db:
        db.add_all(
            [
                Card(id="card-1", name="Shock", layout="normal", rarity="common", legalities={}, color_identity=["R"]),
                Card(
                    id="card-2",
                    name="Lightning Bolt",
                    layout="normal",
                    rarity="common",
                    legalities={},
                    color_identity=["R"],
                ),
                Card(
                    id="card-3",
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
                    card_id="card-1",
                    name="Shock",
                    type_line="Instant",
                    oracle_text="Shock deals 2 damage to any target.",
                    colors=["R"],
                ),
                CardFace(
                    card_id="card-2",
                    name="Lightning Bolt",
                    type_line="Instant",
                    oracle_text="Lightning Bolt deals 3 damage to any target.",
                    colors=["R"],
                ),
                CardFace(
                    card_id="card-3",
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
                CardTagging(id="tagging-1", card_id="card-1", tag_id="tag-1", foreign_key="oracleId"),
                CardTagging(id="tagging-2", card_id="card-2", tag_id="tag-1", foreign_key="oracleId"),
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

    main(["--config", str(config_file), "--runs-dir", str(tmp_path)])

    assert runs[0].epochs == 7


# ---------------------------------------------------------------------------
# Dataset building
# ---------------------------------------------------------------------------


def test_build_dataset_uses_face_ids_and_lazy_text_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_records()
    monkeypatch.setattr("ot_backend.embed.pipeline.random.shuffle", lambda seq: None)

    with SessionLocal() as db:
        state = build_training_dataset_state(db)
        face_rows = db.query(CardFace).order_by(CardFace.id).all()

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
    monkeypatch.setattr("ot_backend.embed.pipeline.random.shuffle", lambda seq: None)

    with SessionLocal() as db:
        db.add_all(
            [
                Tag(id="tag-2", tag_name="foil", tag_namespace="artwork"),
                Tag(id="tag-3", tag_name="tribal", tag_namespace="card"),
            ]
        )
        db.add_all(
            [
                CardTagging(id="tagging-3", card_id="card-1", tag_id="tag-2", foreign_key="oracleId"),
                CardTagging(id="tagging-4", card_id="card-2", tag_id="tag-3", foreign_key="illustrationId"),
            ]
        )
        db.commit()
        state = build_training_dataset_state(db)

    assert state.tag_pair_examples == 1


def test_export_and_load_training_dataset_round_trips(tmp_path: Path) -> None:
    _seed_records()

    with SessionLocal() as db:
        state = build_training_dataset_state(db)

    export_path = tmp_path / "dataset.json"
    export_training_dataset(state, export_path)
    loaded = load_training_dataset(export_path)

    assert loaded == state


# ---------------------------------------------------------------------------
# Pipeline: --no-fine-tune
# ---------------------------------------------------------------------------


def test_pipeline_no_fine_tune_exports_base_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exported: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        "ot_backend.embed.pipeline.export_onnx_model",
        lambda src, out: exported.append((src, out)),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._compute_embeddings", lambda model, batch_size=256: 0)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._load_sentence_transformer_class",
        lambda: (lambda model_name: SimpleNamespace(base_model_name=model_name)),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["--no-fine-tune", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert len(exported) == 1
    base_model = PipelineConfig().base_model
    assert exported[0][0] == base_model


# ---------------------------------------------------------------------------
# Pipeline: full run (fine-tune → embeddings → save → onnx export)
# ---------------------------------------------------------------------------


def test_pipeline_default_fine_tunes_then_computes_embeddings_then_exports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("{}")

    monkeypatch.setattr(
        "ot_backend.embed.pipeline._prepare_and_save_dataset",
        lambda path, config: calls.append(f"prepare:{path}"),
    )
    monkeypatch.setattr(
        "ot_backend.embed.pipeline.load_training_dataset",
        lambda path: calls.append(f"load:{path}") or TrainingDatasetState({}, [], 0, 0),
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
        lambda model, batch_size=256: calls.append("embed") or 3,
    )
    monkeypatch.setattr(
        "ot_backend.embed.pipeline.export_onnx_model",
        lambda src, out: calls.append(f"onnx:{src}"),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert "train" in calls
    assert "embed" in calls
    assert any(c.startswith("onnx:") for c in calls)

    # ONNX export receives the saved PyTorch path, not the base model name
    onnx_call = next(c for c in calls if c.startswith("onnx:"))
    assert "pytorch" in onnx_call

    # Verify run dir artifacts
    run_dir = tmp_path / "test-run"
    assert (run_dir / "config.json").exists()
    assert (run_dir / "metrics.json").exists()

    # Verify latest symlink
    assert (tmp_path / "latest").is_symlink()
    assert (tmp_path / "latest").resolve() == run_dir.resolve()


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

    monkeypatch.setattr("ot_backend.embed.pipeline.SessionLocal", fake_session_local)
    monkeypatch.setattr("ot_backend.embed.pipeline._ensure_training_dependencies", lambda: None)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._load_sentence_transformers",
        lambda: (FakeSentenceTransformer, DummyInputExample, FakeLosses),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline.huggingface_cache_dir", lambda: tmp_path / "hf")
    monkeypatch.setattr("ot_backend.embed.pipeline.import_module", fake_import_module)
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr("ot_backend.embed.pipeline._compute_embeddings", lambda model, batch_size=256: 0)
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["--runs-dir", str(tmp_path)])

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
        "ot_backend.embed.pipeline.SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("DB must not be used")),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._ensure_training_dependencies", lambda: None)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._load_sentence_transformers",
        lambda: (FakeSentenceTransformer, DummyInputExample, FakeLosses),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline.huggingface_cache_dir", lambda: tmp_path / "hf")

    def fake_import_module(name: str) -> Any:
        if name == "torch.utils.data":
            return SimpleNamespace(DataLoader=FakeDataLoader)
        raise AssertionError(f"Unexpected: {name}")

    monkeypatch.setattr("ot_backend.embed.pipeline.import_module", fake_import_module)
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr("ot_backend.embed.pipeline._compute_embeddings", lambda model, batch_size=256: 0)
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["--dataset-path", str(dataset_path), "--runs-dir", str(tmp_path)])

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

    monkeypatch.setattr("ot_backend.embed.pipeline._ensure_training_dependencies", lambda: None)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._load_sentence_transformers",
        lambda: (FakeSentenceTransformer, DummyInputExample, FakeLosses),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline.huggingface_cache_dir", lambda: tmp_path / "hf")
    monkeypatch.setattr("ot_backend.embed.pipeline._is_mps_available", lambda: True)
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr("ot_backend.embed.pipeline._compute_embeddings", lambda model, batch_size=256: 0)
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    def fake_import_module(name: str) -> Any:
        if name == "torch.utils.data":
            return SimpleNamespace(DataLoader=FakeDataLoader)
        raise AssertionError(f"Unexpected: {name}")

    monkeypatch.setattr("ot_backend.embed.pipeline.import_module", fake_import_module)

    exit_code = main(["--runs-dir", str(tmp_path)])

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
        "ot_backend.embed.pipeline._load_sentence_transformer_class", lambda: FakeSentenceTransformer
    )
    monkeypatch.setattr("ot_backend.embed.pipeline.huggingface_cache_dir", lambda: tmp_path / "hf")

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


def test_pipeline_creates_versioned_run_dir_and_latest_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "20260324-120000")
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr("ot_backend.embed.pipeline._compute_embeddings", lambda model, batch_size=256: 0)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._prepare_and_save_dataset",
        lambda path, config: path.write_text(
            '{"version":1,"face_texts":[],"pair_ids":[],"simcse_examples":0,"tag_pair_examples":0}',
            encoding="utf-8",
        ),
    )

    class FakeModel:
        def save(self, path: str) -> None:
            pass

    monkeypatch.setattr(
        "ot_backend.embed.pipeline._train",
        lambda config, state, run_dir: FakeModel(),
    )

    exit_code = main(["--runs-dir", str(tmp_path)])

    assert exit_code == 0
    run_dir = tmp_path / "20260324-120000"
    assert run_dir.is_dir()
    assert (run_dir / "config.json").exists()
    assert (run_dir / "metrics.json").exists()
    latest = tmp_path / "latest"
    assert latest.is_symlink()
    assert latest.resolve() == run_dir.resolve()


# ---------------------------------------------------------------------------
# --no-embeddings flag
# ---------------------------------------------------------------------------


def test_pipeline_no_embeddings_skips_compute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    compute_calls: list[Any] = []
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._compute_embeddings",
        lambda model, batch_size=256: compute_calls.append(model) or 0,
    )
    monkeypatch.setattr("ot_backend.embed.pipeline.export_onnx_model", lambda src, out: None)
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._prepare_and_save_dataset",
        lambda path, config: path.write_text(
            '{"version":1,"face_texts":[],"pair_ids":[],"simcse_examples":0,"tag_pair_examples":0}',
            encoding="utf-8",
        ),
    )

    class FakeModel:
        def save(self, path: str) -> None:
            pass

    monkeypatch.setattr(
        "ot_backend.embed.pipeline._train",
        lambda config, state, run_dir: FakeModel(),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._make_run_id", lambda name=None: "test-run")

    exit_code = main(["--no-embeddings", "--runs-dir", str(tmp_path)])

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
        lambda model, batch_size=256: embedded.append(model) or 5,
    )

    exit_code = main(["--reembed-only", "--base-model", str(model_dir), "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert loaded == [str(model_dir)]
    assert len(embedded) == 1
    # No run dirs or latest symlink created
    assert not (tmp_path / "latest").exists()
    assert not any((tmp_path / d).is_dir() for d in ["pytorch", "onnx"])


def test_reembed_only_defaults_to_latest_pytorch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    latest_pytorch = tmp_path / "latest" / "pytorch"
    latest_pytorch.mkdir(parents=True)

    loaded: list[str] = []
    monkeypatch.setattr(
        "ot_backend.embed.pipeline._load_sentence_transformer_class",
        lambda: (lambda path: loaded.append(path) or object()),
    )
    monkeypatch.setattr("ot_backend.embed.pipeline._compute_embeddings", lambda model, batch_size=256: 0)

    exit_code = main(["--reembed-only", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    assert loaded == [str(tmp_path / "latest" / "pytorch")]
