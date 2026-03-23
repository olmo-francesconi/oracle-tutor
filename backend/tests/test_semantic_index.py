from __future__ import annotations

from types import SimpleNamespace

from ot_backend.embed import index


def test_get_semantic_index_falls_back_to_base_model(monkeypatch) -> None:
    index._index = None

    loaded_model_sources: list[str] = []

    class FakeSentenceTransformer:
        def __init__(self, model_source: str) -> None:
            loaded_model_sources.append(model_source)

    monkeypatch.setattr("ot_backend.embed.index.huggingface_cache_dir", lambda: None)
    monkeypatch.setattr("ot_backend.embed.index.semantic_model_source", lambda: "sentence-transformers/test-model")
    monkeypatch.setattr(
        "ot_backend.embed.index.import_module",
        lambda module_name: SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    semantic_index = index.get_semantic_index()

    assert semantic_index is not None
    assert loaded_model_sources == ["sentence-transformers/test-model"]
    index._index = None
