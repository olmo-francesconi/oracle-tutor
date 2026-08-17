"""Access to the optional sentence-transformers dependency.

Training itself runs on Modal (`semantic/modal_train.py`); what remains here is
the guarded import that promotion needs to load a bundle.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


def _load_sentence_transformers() -> tuple[Any, Any, Any]:
    try:
        st = import_module("sentence_transformers")
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "sentence-transformers is required for this pipeline. "
            "Install the semantic-worker extra before running."
        ) from exc
    return getattr(st, "SentenceTransformer"), getattr(st, "InputExample"), getattr(st, "losses")


def load_sentence_transformer_class() -> Any:
    return _load_sentence_transformers()[0]
