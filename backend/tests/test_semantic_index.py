from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from ot_backend.semantic import index


def _make_fake_session(model_id: int):
    """Return a fake SessionLocal context manager that yields a mock db."""
    fake_model = MagicMock()
    fake_model.id = model_id

    @contextmanager
    def fake_session_local():
        mock_db = MagicMock()
        mock_db.get.return_value = fake_model
        yield mock_db

    return fake_session_local


def _make_lookup_session():
    @contextmanager
    def fake_session_local():
        mock_db = MagicMock()

        def fake_get(_model_cls, model_id: int):
            fake_model = MagicMock()
            fake_model.id = model_id
            return fake_model

        mock_db.get.side_effect = fake_get
        yield mock_db

    return fake_session_local


def _reset_index_state() -> None:
    index._index = None
    index._last_refresh_check = 0.0
    index._loaded_model_id = index._UNSET


def test_get_semantic_index_uses_onnx_runtime_and_tokenizer(monkeypatch, tmp_path) -> None:
    _reset_index_state()

    model_root = tmp_path / "semantic-model"
    pooling_dir = model_root / "1_Pooling"
    pooling_dir.mkdir(parents=True)
    (model_root / "onnx").mkdir(parents=True)
    (model_root / "onnx" / "model.onnx").write_bytes(b"onnx")
    (pooling_dir / "config.json").write_text('{"pooling_mode_mean_tokens": true}', encoding="utf-8")

    import_calls: list[str] = []
    tokenizer_paths: list[str] = []
    session_paths: list[str] = []

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, path: str, local_files_only: bool) -> "FakeTokenizer":
            tokenizer_paths.append(path)
            assert local_files_only is True
            return cls()

        def __call__(self, texts: list[str], **_: object) -> dict[str, np.ndarray]:
            assert texts == ["Deal damage to any target."]
            return {
                "input_ids": np.asarray([[101, 102, 0]], dtype=np.int64),
                "attention_mask": np.asarray([[1, 1, 0]], dtype=np.int64),
                "token_type_ids": np.asarray([[0, 0, 0]], dtype=np.int64),
            }

    class FakeSessionInput:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeSessionOptions:
        def __init__(self) -> None:
            self.log_severity_level = 0
            self.intra_op_num_threads = 0
            self.inter_op_num_threads = 0

    class FakeInferenceSession:
        def __init__(self, path: str, *, sess_options: FakeSessionOptions, providers: list[str]) -> None:
            session_paths.append(path)
            assert providers == ["CPUExecutionProvider"]
            assert sess_options.log_severity_level == 3
            assert sess_options.intra_op_num_threads == 2
            assert sess_options.inter_op_num_threads == 3

        def get_inputs(self) -> list[FakeSessionInput]:
            return [FakeSessionInput("input_ids"), FakeSessionInput("attention_mask")]

        def run(self, _output_names: object, inputs: dict[str, np.ndarray]) -> list[np.ndarray]:
            assert "token_type_ids" not in inputs
            assert inputs["input_ids"].shape == (1, 3)
            return [
                np.asarray(
                    [[[1.0, 0.0], [0.0, 1.0], [10.0, 10.0]]],
                    dtype=np.float32,
                )
            ]

    def fake_import_module(module_name: str) -> object:
        import_calls.append(module_name)
        if module_name == "onnxruntime":
            return SimpleNamespace(InferenceSession=FakeInferenceSession, SessionOptions=FakeSessionOptions)
        if module_name == "transformers":
            return SimpleNamespace(AutoTokenizer=FakeTokenizer)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr("ot_backend.semantic.index.get_active_semantic_model_id", lambda db: 1)
    monkeypatch.setattr("ot_backend.semantic.index.SessionLocal", _make_fake_session(1))
    monkeypatch.setattr(
        "ot_backend.semantic.index.materialize_semantic_model",
        lambda model, **kw: (model_root, model_root),
    )
    monkeypatch.setattr("ot_backend.semantic.index.import_module", fake_import_module)
    monkeypatch.setattr("ot_backend.semantic.index.configure_huggingface_env", lambda: None)
    monkeypatch.setenv("SEMANTIC_ONNX_INTRA_OP_THREADS", "2")
    monkeypatch.setenv("SEMANTIC_ONNX_INTER_OP_THREADS", "3")

    semantic_index = index.get_semantic_index()

    assert semantic_index is not None
    query_embedding = semantic_index.encode_query("Deal damage to any target.")
    assert tokenizer_paths == [str(model_root)]
    assert session_paths == [str(model_root / "onnx" / "model.onnx")]
    assert import_calls == ["onnxruntime", "transformers"]
    assert query_embedding == [0.7071067690849304, 0.7071067690849304]
    _reset_index_state()


def test_get_semantic_index_returns_none_when_onnx_artifact_is_missing(monkeypatch, tmp_path) -> None:
    _reset_index_state()

    model_root = tmp_path / "semantic-model"
    model_root.mkdir(parents=True)

    monkeypatch.setattr("ot_backend.semantic.index.get_active_semantic_model_id", lambda db: 1)
    monkeypatch.setattr("ot_backend.semantic.index.SessionLocal", _make_fake_session(1))
    monkeypatch.setattr(
        "ot_backend.semantic.index.materialize_semantic_model",
        lambda model, **kw: (model_root, model_root),
    )

    semantic_index = index.get_semantic_index()

    assert semantic_index is None
    _reset_index_state()


def test_get_semantic_index_rejects_unsupported_pooling(monkeypatch, tmp_path) -> None:
    _reset_index_state()

    model_root = tmp_path / "semantic-model"
    pooling_dir = model_root / "1_Pooling"
    pooling_dir.mkdir(parents=True)
    (model_root / "onnx").mkdir(parents=True)
    (model_root / "onnx" / "model.onnx").write_bytes(b"onnx")
    (pooling_dir / "config.json").write_text('{"pooling_mode_cls_token": true}', encoding="utf-8")

    monkeypatch.setattr("ot_backend.semantic.index.get_active_semantic_model_id", lambda db: 1)
    monkeypatch.setattr("ot_backend.semantic.index.SessionLocal", _make_fake_session(1))
    monkeypatch.setattr(
        "ot_backend.semantic.index.materialize_semantic_model",
        lambda model, **kw: (model_root, model_root),
    )

    semantic_index = index.get_semantic_index()

    assert semantic_index is None
    _reset_index_state()


def test_get_semantic_index_clears_stale_cache_when_active_model_changes_and_reload_fails(monkeypatch, tmp_path) -> None:
    _reset_index_state()

    model_root = tmp_path / "semantic-model"
    pooling_dir = model_root / "1_Pooling"
    pooling_dir.mkdir(parents=True)
    (model_root / "onnx").mkdir(parents=True)
    (model_root / "onnx" / "model.onnx").write_bytes(b"onnx")
    (pooling_dir / "config.json").write_text('{"pooling_mode_mean_tokens": true}', encoding="utf-8")

    model_ids = iter([1, 2])
    monkeypatch.setattr("ot_backend.semantic.index.get_active_semantic_model_id", lambda db: next(model_ids))
    monkeypatch.setattr("ot_backend.semantic.index.SessionLocal", _make_lookup_session())
    monkeypatch.setattr("ot_backend.semantic.index.semantic_active_model_poll_seconds", lambda: 0.0)
    monkeypatch.setattr(
        "ot_backend.semantic.index.materialize_semantic_model",
        lambda model, **kw: (model_root, model_root) if model.id == 1 else (_ for _ in ()).throw(RuntimeError("broken bundle")),
    )

    class FakeSemanticIndex:
        def __init__(self, model_root, model_id=None):
            self.model_root = model_root
            self.model_id = model_id

    monkeypatch.setattr("ot_backend.semantic.index.SemanticIndex", FakeSemanticIndex)

    first_index = index.get_semantic_index()
    second_index = index.get_semantic_index()

    assert first_index is not None
    assert first_index.model_id == 1
    assert second_index is None
    assert index._index is None
    assert index._loaded_model_id == 2


def test_get_semantic_index_clears_cache_when_no_active_model_exists(monkeypatch, tmp_path) -> None:
    _reset_index_state()

    model_root = tmp_path / "semantic-model"
    pooling_dir = model_root / "1_Pooling"
    pooling_dir.mkdir(parents=True)
    (model_root / "onnx").mkdir(parents=True)
    (model_root / "onnx" / "model.onnx").write_bytes(b"onnx")
    (pooling_dir / "config.json").write_text('{"pooling_mode_mean_tokens": true}', encoding="utf-8")

    model_ids = iter([1, None])
    monkeypatch.setattr("ot_backend.semantic.index.get_active_semantic_model_id", lambda db: next(model_ids))
    monkeypatch.setattr("ot_backend.semantic.index.SessionLocal", _make_fake_session(1))
    monkeypatch.setattr("ot_backend.semantic.index.semantic_active_model_poll_seconds", lambda: 0.0)
    monkeypatch.setattr(
        "ot_backend.semantic.index.materialize_semantic_model",
        lambda model, **kw: (model_root, model_root),
    )

    class FakeSemanticIndex:
        def __init__(self, model_root, model_id=None):
            self.model_root = model_root
            self.model_id = model_id

    monkeypatch.setattr("ot_backend.semantic.index.SemanticIndex", FakeSemanticIndex)

    first_index = index.get_semantic_index()
    second_index = index.get_semantic_index()

    assert first_index is not None
    assert second_index is None
    assert index._index is None
    assert index._loaded_model_id is None
