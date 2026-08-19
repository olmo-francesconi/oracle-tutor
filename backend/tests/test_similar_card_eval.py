"""Tests for the external-ground-truth similarity benchmark.

The point of this set is that its relationships come from outside the project —
Wizards' templating and published community lists — so the tests guard the two
ways it could quietly stop meaning that: silently skipping cases, and judging
identical-text cards by an ordinal rank that is arbitrary among ties.
"""

from __future__ import annotations

import json
from importlib.resources import files

from ot_backend.semantic.similar_card_eval import RANK_TARGETS, load_reference


def test_the_reference_loads_and_every_case_has_a_known_category() -> None:
    cases = load_reference()

    assert len(cases) >= 20
    for case in cases:
        assert case.category in RANK_TARGETS, f"{case.seed}: unknown category {case.category}"
        assert case.expect, f"{case.seed} expects nothing"
        assert case.seed not in case.expect, f"{case.seed} expects itself"


def test_targets_get_looser_as_the_claim_gets_weaker() -> None:
    """A functional reprint shares near-identical text and has no excuse; a
    community budget swap is a judgement call and only needs to place."""
    assert RANK_TARGETS["functional_reprint"] < RANK_TARGETS["cycle"]
    assert RANK_TARGETS["cycle"] < RANK_TARGETS["near_equivalent"]
    assert RANK_TARGETS["near_equivalent"] < RANK_TARGETS["budget_swap"]


def test_the_titans_are_absent() -> None:
    """They share a trigger clause and nothing else — a cycle by rarity and
    size, not by text. Expecting them to match would encode a wrong belief."""
    seeds = {case.seed for case in load_reference()}

    assert "Sun Titan" not in seeds


def test_every_category_is_actually_exercised() -> None:
    used = {case.category for case in load_reference()}

    assert used == set(RANK_TARGETS), f"unused categories: {set(RANK_TARGETS) - used}"


def test_the_reference_file_documents_the_tie_rule() -> None:
    """366 vanilla faces share one placeholder text; anyone reading the results
    needs to know why ordinal rank is not the pass criterion."""
    raw = files("ot_backend.semantic").joinpath("similar_card_reference.json").read_bytes()

    assert "tie" in json.loads(raw)["description"].lower()
