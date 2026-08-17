"""The `eval_queries.json` bundle payload.

Only the shipped queries file and the summary reader survive: scoring is done
by `semantic/tag_eval.py`, which runs held-out tags through the real retrieval
path instead of cosine over face text.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any


def default_eval_queries_bytes() -> bytes:
    return files("ot_backend.semantic").joinpath("eval_queries.json").read_bytes()


def summarize_eval_payload(eval_payload: dict[str, Any]) -> dict[str, object]:
    summary = eval_payload.get("summary")
    if not isinstance(summary, dict):
        return {}
    return {str(key): value for key, value in summary.items()}
