from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import init_db
from ot_backend.core.models import Card, CardFace, CardTagging, Tag
from ot_backend.embed.train import (
    LazyInputExampleDataset,
    build_training_dataset_state,
    export_training_dataset,
    load_training_dataset,
    main,
)
from ot_backend.embed.text_prep import face_to_text


@dataclass
class DummyInputExample:
    texts: list[str]


def _reset_training_tables() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(CardTagging).delete()
        db.query(Tag).delete()
        db.query(CardFace).delete()
        db.query(Card).delete()
        db.commit()


def _seed_training_records() -> None:
    _reset_training_tables()
    with SessionLocal() as db:
        db.add_all(
            [
                Card(id="card-1", name="Shock", layout="normal", rarity="common", legalities={}, color_identity=["R"]),
                Card(id="card-2", name="Lightning Bolt", layout="normal", rarity="common", legalities={}, color_identity=["R"]),
                Card(id="card-3", name="Llanowar Elves", layout="normal", rarity="common", legalities={}, color_identity=["G"]),
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
        face_by_card_id = {face.card_id: face.id for face in db.query(CardFace).all()}
        db.add_all(
            [
                CardTagging(id="tagging-1", card_id="card-1", tag_id="tag-1", foreign_key="oracleId"),
                CardTagging(id="tagging-2", card_id="card-2", tag_id="tag-1", foreign_key="oracleId"),
            ]
        )
        db.commit()

    assert face_by_card_id["card-1"] != face_by_card_id["card-2"]


def test_build_training_dataset_state_uses_face_ids_and_lazy_text_resolution(monkeypatch) -> None:
    _seed_training_records()
    monkeypatch.setattr("ot_backend.embed.train.random.shuffle", lambda seq: None)

    with SessionLocal() as db:
        dataset_state = build_training_dataset_state(db)

        face_rows = db.query(CardFace).order_by(CardFace.id).all()

    assert len(dataset_state.face_texts) == 3
    assert dataset_state.simcse_examples == 3
    assert dataset_state.tag_pair_examples == 1
    assert len(dataset_state.pair_ids) == 4
    assert all(isinstance(left_id, int) and isinstance(right_id, int) for left_id, right_id in dataset_state.pair_ids)

    dataset = LazyInputExampleDataset(dataset_state.pair_ids, dataset_state.face_texts, DummyInputExample)
    self_pair = dataset[0]
    tag_pair = dataset[-1]

    assert self_pair.texts[0] == self_pair.texts[1]
    assert self_pair.texts[0] == face_to_text(face_rows[0])
    assert tag_pair.texts == [face_to_text(face_rows[0]), face_to_text(face_rows[1])]


def test_build_training_dataset_state_ignores_non_card_or_non_oracle_tags(monkeypatch) -> None:
    _seed_training_records()
    monkeypatch.setattr("ot_backend.embed.train.random.shuffle", lambda seq: None)

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

        dataset_state = build_training_dataset_state(db)

    assert dataset_state.tag_pair_examples == 1


def test_export_and_load_training_dataset_round_trips(tmp_path) -> None:
    _seed_training_records()

    with SessionLocal() as db:
        dataset_state = build_training_dataset_state(db)

    export_path = tmp_path / "semantic-training.json"
    export_training_dataset(dataset_state, export_path)
    loaded_state = load_training_dataset(export_path)

    assert loaded_state == dataset_state


def test_main_builds_lazy_dataset_and_closes_session_before_fit(monkeypatch, tmp_path) -> None:
    _seed_training_records()

    class RecordingSession:
        def __init__(self, session: Any) -> None:
            self._session = session
            self.closed = False

        def execute(self, *args: Any, **kwargs: Any) -> Any:
            return self._session.execute(*args, **kwargs)

        def close(self) -> None:
            self.closed = True
            self._session.close()

    class FakeDataLoader:
        def __init__(self, dataset: Any, shuffle: bool, batch_size: int) -> None:
            self.dataset = dataset
            self.shuffle = shuffle
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
            self.session_closed_during_fit = False
            FakeSentenceTransformer.instances.append(self)

        def fit(self, **kwargs: Any) -> None:
            self.fit_calls.append(kwargs)
            self.session_closed_during_fit = recording_session.closed

        def save(self, path: str) -> None:
            self.saved_path = path

    real_session = SessionLocal()
    recording_session = RecordingSession(real_session)

    monkeypatch.setattr("ot_backend.embed.train.SessionLocal", lambda: recording_session)
    monkeypatch.setattr("ot_backend.embed.train._ensure_training_dependencies", lambda: None)
    monkeypatch.setattr(
        "ot_backend.embed.train._load_sentence_transformers",
        lambda: (FakeSentenceTransformer, DummyInputExample, FakeLosses),
    )
    monkeypatch.setattr("ot_backend.embed.train.huggingface_cache_dir", lambda: tmp_path / "hf-cache")
    monkeypatch.setattr("ot_backend.embed.train.semantic_model_path", lambda: tmp_path / "semantic-model")

    def fake_import_module(module_name: str) -> Any:
        if module_name == "torch.utils.data":
            return SimpleNamespace(DataLoader=FakeDataLoader)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr("ot_backend.embed.train.import_module", fake_import_module)

    exit_code = main()

    assert exit_code == 0
    assert recording_session.closed is True
    assert len(FakeSentenceTransformer.instances) == 1

    model = FakeSentenceTransformer.instances[0]
    assert model.session_closed_during_fit is True
    assert model.saved_path == str(Path(tmp_path / "semantic-model"))
    assert len(model.fit_calls) == 1

    fit_call = model.fit_calls[0]
    dataloader, loss = fit_call["train_objectives"][0]
    assert isinstance(dataloader.dataset, LazyInputExampleDataset)
    assert dataloader.shuffle is False
    assert loss == f"loss-for-{model.base_model_name}"


def test_main_can_train_from_exported_dataset_without_db(monkeypatch, tmp_path) -> None:
    _seed_training_records()

    with SessionLocal() as db:
        dataset_state = build_training_dataset_state(db)

    export_path = tmp_path / "semantic-training.json"
    export_training_dataset(dataset_state, export_path)

    class FakeDataLoader:
        def __init__(self, dataset: Any, shuffle: bool, batch_size: int) -> None:
            self.dataset = dataset
            self.shuffle = shuffle
            self.batch_size = batch_size

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
            FakeSentenceTransformer.instances.append(self)

        def fit(self, **kwargs: Any) -> None:
            self.fit_calls.append(kwargs)

        def save(self, path: str) -> None:
            self.saved_path = path

    monkeypatch.setattr("ot_backend.embed.train.SessionLocal", lambda: (_ for _ in ()).throw(AssertionError("DB should not be used")))
    monkeypatch.setattr("ot_backend.embed.train._ensure_training_dependencies", lambda: None)
    monkeypatch.setattr(
        "ot_backend.embed.train._load_sentence_transformers",
        lambda: (FakeSentenceTransformer, DummyInputExample, FakeLosses),
    )
    monkeypatch.setattr("ot_backend.embed.train.huggingface_cache_dir", lambda: tmp_path / "hf-cache")

    def fake_import_module(module_name: str) -> Any:
        if module_name == "torch.utils.data":
            return SimpleNamespace(DataLoader=FakeDataLoader)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr("ot_backend.embed.train.import_module", fake_import_module)

    output_path = tmp_path / "colab-model"
    exit_code = main(["--dataset-path", str(export_path), "--output-path", str(output_path)])

    assert exit_code == 0
    assert len(FakeSentenceTransformer.instances) == 1
    assert FakeSentenceTransformer.instances[0].saved_path == str(output_path)
