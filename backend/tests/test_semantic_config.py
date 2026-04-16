import os
from pathlib import Path

from ot_backend.core.config import (
    configure_huggingface_env,
    huggingface_cache_dir,
    semantic_active_model_poll_seconds,
    semantic_base_model_name,
    semantic_temp_dir,
)


def test_huggingface_cache_dir_defaults_to_writable_data_path(monkeypatch, tmp_path):
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("TRANSFORMERS_CACHE", raising=False)
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)
    monkeypatch.setattr("ot_backend.core.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("ot_backend.core.config.DEFAULT_HF_CACHE_DIR", tmp_path / "huggingface")

    cache_dir = huggingface_cache_dir()
    configure_huggingface_env()

    assert cache_dir == tmp_path / "huggingface"
    assert cache_dir.exists()
    assert "TRANSFORMERS_CACHE" not in os.environ
    assert Path(cache_dir, "sentence-transformers") == Path(os.environ["SENTENCE_TRANSFORMERS_HOME"])


def test_semantic_base_model_name_reads_env(monkeypatch):
    monkeypatch.setenv("SEMANTIC_BASE_MODEL", "sentence-transformers/test-model")

    assert semantic_base_model_name() == "sentence-transformers/test-model"


def test_semantic_active_model_poll_seconds_reads_env(monkeypatch):
    monkeypatch.setenv("SEMANTIC_ACTIVE_MODEL_POLL_SECONDS", "1.5")

    assert semantic_active_model_poll_seconds() == 1.5


def test_semantic_temp_dir_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SEMANTIC_TEMP_DIR", str(tmp_path / "semantic-cache"))

    assert semantic_temp_dir() == tmp_path / "semantic-cache"
