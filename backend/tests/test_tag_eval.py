"""Tests for the held-out-tag evaluation harness.

The point of this harness is that it cannot be gamed by memorisation, so the
tests concentrate on the split being stable and the metrics being honest about
tags larger than the result list.
"""

from __future__ import annotations

import json
from importlib.resources import files

import pytest

from ot_backend.semantic.tag_eval import (
    DEFAULT_HOLDOUT_PERCENT,
    _metrics_for,
    is_held_out_tag,
    load_paraphrases,
)

# ---------------------------------------------------------------------------
# The split
# ---------------------------------------------------------------------------


def test_the_split_is_stable_across_runs() -> None:
    """It is recomputed by the trainer and the evaluator independently."""
    for name in ["mana dork", "burn-you", "gains lifelink", "a" * 200]:
        assert is_held_out_tag(name) == is_held_out_tag(name)


def test_the_split_lands_near_the_requested_share() -> None:
    names = [f"tag-{i}" for i in range(4000)]
    held = sum(1 for n in names if is_held_out_tag(n))

    assert abs(held / len(names) * 100 - DEFAULT_HOLDOUT_PERCENT) < 2.0


def test_a_zero_percent_holdout_disables_the_split() -> None:
    """So a run can deliberately train on everything."""
    assert not any(is_held_out_tag(f"tag-{i}", holdout_percent=0) for i in range(500))


def test_different_percentages_are_nested() -> None:
    """Widening the holdout must not move tags back into training."""
    names = [f"tag-{i}" for i in range(2000)]
    narrow = {n for n in names if is_held_out_tag(n, holdout_percent=10)}
    wide = {n for n in names if is_held_out_tag(n, holdout_percent=25)}

    assert narrow < wide


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_mrr_uses_the_first_relevant_result() -> None:
    m = _metrics_for(["x", "y", "gold1", "gold2"], frozenset({"gold1", "gold2"}))

    assert m["mrr"] == pytest.approx(1 / 3)


def test_no_relevant_result_scores_zero_not_an_error() -> None:
    m = _metrics_for(["x", "y"], frozenset({"gold"}))

    assert m["mrr"] == 0.0
    assert m["p_at_10"] == 0.0
    assert m["recall_at_100"] == 0.0


def test_precision_at_10_ignores_results_past_the_tenth() -> None:
    ranked = ["gold"] * 5 + ["x"] * 5 + ["gold"] * 50

    assert _metrics_for(ranked, frozenset({"gold"}))["p_at_10"] == pytest.approx(0.5)


def test_recall_is_capped_so_a_big_tag_is_not_punished_for_its_size() -> None:
    """A 400-card tag cannot fit in a 100-long list; scoring it 0.25 would
    measure the tag's size rather than the ranking's quality."""
    gold = frozenset(f"c{i}" for i in range(400))
    ranked = [f"c{i}" for i in range(100)]

    assert _metrics_for(ranked, gold)["recall_at_100"] == pytest.approx(1.0)


def test_recall_is_a_true_fraction_for_a_small_tag() -> None:
    gold = frozenset({"a", "b", "c", "d"})

    assert _metrics_for(["a", "b", "z"], gold)["recall_at_100"] == pytest.approx(0.5)


def test_an_empty_result_list_is_handled() -> None:
    assert _metrics_for([], frozenset({"a"}))["mrr"] == 0.0


# ---------------------------------------------------------------------------
# Paraphrases
# ---------------------------------------------------------------------------


def test_paraphrases_load_and_are_not_just_the_slug() -> None:
    """A paraphrase that restates the tag name tests nothing."""
    paraphrases = load_paraphrases()

    assert len(paraphrases) >= 20
    for phrase, tag_name in paraphrases.items():
        assert phrase.strip().lower() != tag_name.strip().lower()


def test_the_paraphrase_file_is_valid_json_with_a_description() -> None:
    raw = files("ot_backend.semantic").joinpath("tag_eval_paraphrases.json").read_bytes()
    payload = json.loads(raw)

    assert payload["description"]
    assert isinstance(payload["paraphrases"], dict)
