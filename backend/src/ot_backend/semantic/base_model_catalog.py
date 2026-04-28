from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemanticBaseModelSpec:
    key: str
    label: str
    base_model: str
    embedding_dim: int
    enabled: bool = True


_SEMANTIC_BASE_MODELS: tuple[SemanticBaseModelSpec, ...] = (
    SemanticBaseModelSpec(
        key="mini-lm-l6-v2",
        label="MiniLM L6 v2",
        base_model="sentence-transformers/all-MiniLM-L6-v2",
        embedding_dim=384,
    ),
    SemanticBaseModelSpec(
        key="mini-lm-l12-v2",
        label="MiniLM L12 v2",
        base_model="sentence-transformers/all-MiniLM-L12-v2",
        embedding_dim=384,
    ),
    SemanticBaseModelSpec(
        key="paraphrase-mini-lm-l6-v2",
        label="Paraphrase MiniLM L6 v2",
        base_model="sentence-transformers/paraphrase-MiniLM-L6-v2",
        embedding_dim=384,
    ),
)


def list_semantic_base_models(*, include_disabled: bool = False) -> list[SemanticBaseModelSpec]:
    if include_disabled:
        return list(_SEMANTIC_BASE_MODELS)
    return [spec for spec in _SEMANTIC_BASE_MODELS if spec.enabled]


def get_semantic_base_model(key: str) -> SemanticBaseModelSpec:
    normalized_key = key.strip()
    for spec in _SEMANTIC_BASE_MODELS:
        if spec.key == normalized_key:
            if not spec.enabled:
                raise ValueError(f"Semantic base model '{normalized_key}' is disabled.")
            return spec
    raise ValueError(f"Unknown semantic base model '{normalized_key}'.")
