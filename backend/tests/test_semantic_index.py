from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from ot_backend.embed import index


def test_get_semantic_index_uses_onnx_runtime_and_tokenizer(monkeypatch, tmp_path) -> None:
    index._index = None

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

    class FakeInferenceSession:
        def __init__(self, path: str, providers: list[str]) -> None:
            session_paths.append(path)
            assert providers == ["CPUExecutionProvider"]

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
            return SimpleNamespace(InferenceSession=FakeInferenceSession)
        if module_name == "transformers":
            return SimpleNamespace(AutoTokenizer=FakeTokenizer)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr("ot_backend.embed.index.import_module", fake_import_module)
    monkeypatch.setattr("ot_backend.embed.index.huggingface_cache_dir", lambda: None)
    monkeypatch.setattr("ot_backend.embed.index.semantic_model_path", lambda: model_root)
    monkeypatch.setattr("ot_backend.embed.index.semantic_onnx_model_path", lambda: model_root / "onnx" / "model.onnx")

    semantic_index = index.get_semantic_index()

    assert semantic_index is not None
    query_embedding = semantic_index.encode_query("Deal damage to any target.")
    assert tokenizer_paths == [str(model_root)]
    assert session_paths == [str(model_root / "onnx" / "model.onnx")]
    assert import_calls == ["onnxruntime", "transformers"]
    assert query_embedding == [0.7071067690849304, 0.7071067690849304]
    index._index = None


def test_get_semantic_index_returns_none_when_onnx_artifact_is_missing(monkeypatch, tmp_path) -> None:
    index._index = None

    model_root = tmp_path / "semantic-model"
    model_root.mkdir(parents=True)
    monkeypatch.setattr("ot_backend.embed.index.semantic_model_path", lambda: model_root)
    monkeypatch.setattr("ot_backend.embed.index.semantic_onnx_model_path", lambda: model_root / "onnx" / "model.onnx")

    semantic_index = index.get_semantic_index()

    assert semantic_index is None
    index._index = None


def test_get_semantic_index_rejects_unsupported_pooling(monkeypatch, tmp_path) -> None:
    index._index = None

    model_root = tmp_path / "semantic-model"
    pooling_dir = model_root / "1_Pooling"
    pooling_dir.mkdir(parents=True)
    (model_root / "onnx").mkdir(parents=True)
    (model_root / "onnx" / "model.onnx").write_bytes(b"onnx")
    (pooling_dir / "config.json").write_text('{"pooling_mode_cls_token": true}', encoding="utf-8")

    monkeypatch.setattr("ot_backend.embed.index.semantic_model_path", lambda: model_root)
    monkeypatch.setattr("ot_backend.embed.index.semantic_onnx_model_path", lambda: model_root / "onnx" / "model.onnx")

    semantic_index = index.get_semantic_index()

    assert semantic_index is None
    index._index = None
