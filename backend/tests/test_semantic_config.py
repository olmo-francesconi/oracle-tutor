import os
from pathlib import Path

from ot_backend.core.config import (
    huggingface_cache_dir,
    semantic_base_model_name,
    semantic_model_path,
    semantic_model_source,
    semantic_onnx_model_path,
)


def test_huggingface_cache_dir_defaults_to_writable_data_path(monkeypatch, tmp_path):
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("TRANSFORMERS_CACHE", raising=False)
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)
    monkeypatch.setattr("ot_backend.core.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("ot_backend.core.config.DEFAULT_HF_CACHE_DIR", tmp_path / "huggingface")

    cache_dir = huggingface_cache_dir()

    assert cache_dir == tmp_path / "huggingface"
    assert cache_dir.exists()
    assert Path(cache_dir, "transformers") == Path(os.environ["TRANSFORMERS_CACHE"])
    assert Path(cache_dir, "sentence-transformers") == Path(os.environ["SENTENCE_TRANSFORMERS_HOME"])


def test_semantic_model_path_uses_env_override(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MODEL_PATH", "/tmp/semantic-model")

    assert semantic_model_path() == Path("/tmp/semantic-model")


def test_semantic_model_source_prefers_local_model_path(monkeypatch, tmp_path):
    model_path = tmp_path / "semantic-model"
    model_path.mkdir(parents=True)
    monkeypatch.setenv("SEMANTIC_MODEL_PATH", str(model_path))
    monkeypatch.setenv("SEMANTIC_BASE_MODEL", "sentence-transformers/test-model")

    assert semantic_model_source() == str(model_path)


def test_semantic_model_source_falls_back_to_base_model(monkeypatch, tmp_path):
    monkeypatch.setenv("SEMANTIC_MODEL_PATH", str(tmp_path / "missing-model"))
    monkeypatch.setenv("SEMANTIC_BASE_MODEL", "sentence-transformers/test-model")

    assert semantic_base_model_name() == "sentence-transformers/test-model"
    assert semantic_model_source() == "sentence-transformers/test-model"


def test_semantic_onnx_model_path_uses_conventional_location(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MODEL_PATH", "/tmp/semantic-model")

    assert semantic_onnx_model_path() == Path("/tmp/semantic-model/onnx/model.onnx")


def test_semantic_onnx_model_path_supports_legacy_root_file(monkeypatch, tmp_path):
    model_path = tmp_path / "semantic-model"
    model_path.mkdir(parents=True)
    legacy_file = model_path / "model.onnx"
    legacy_file.write_bytes(b"legacy")
    monkeypatch.setenv("SEMANTIC_MODEL_PATH", str(model_path))

    assert semantic_onnx_model_path() == legacy_file
