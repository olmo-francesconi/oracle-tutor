from __future__ import annotations

from ot_backend.embed.query_gen import generate_template_queries


def test_generate_template_queries_adds_fallbacks_for_emptyoracle() -> None:
    assert generate_template_queries("emptyoracle") == [
        "no rules text",
        "no oracle text",
        "vanilla card",
    ]
