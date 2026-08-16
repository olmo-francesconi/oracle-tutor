"""Tests for how a tag is turned into training anchors.

The bug these pin down: the dataset previously taught a tag *only* through
"name. description". The bare name — the string a player actually types — was
never an anchor, so "mana dork" was left to whatever else happened to use those
words. In the shipped model it had been claimed by a template rule matching
"Add one green mana", which also fires on lands, so the query returned lands.
"""

from __future__ import annotations

import pytest

from ot_backend.semantic.dataset_service import _tag_anchors


def test_a_described_tag_is_taught_by_both_forms() -> None:
    anchors = _tag_anchors("mana dork", "Low-cost creatures which can repeatedly generate mana")

    assert anchors == [
        "mana dork",
        "mana dork. Low-cost creatures which can repeatedly generate mana",
    ]


def test_the_bare_name_is_always_first() -> None:
    """It is the query form, so it must exist even when a description does."""
    for name, desc in [("wrath", "Board wipes."), ("cantrip", "Draws a card.")]:
        assert _tag_anchors(name, desc)[0] == name


def test_an_undescribed_tag_yields_one_anchor() -> None:
    """71% of card tags have no description; they must not emit a duplicate."""
    assert _tag_anchors("mana dork", None) == ["mana dork"]
    assert _tag_anchors("mana dork", "") == ["mana dork"]


@pytest.mark.parametrize("raw", ["mana-dork", "mana_dork", "mana dork"])
def test_separators_normalize_to_the_typed_form(raw: str) -> None:
    """Scryfall slugs use hyphens; a player types spaces."""
    assert _tag_anchors(raw, None) == ["mana dork"]


def test_a_description_equal_to_the_name_is_not_duplicated() -> None:
    assert _tag_anchors("flying", "") == ["flying"]


def test_blank_tag_names_produce_no_anchor() -> None:
    assert _tag_anchors("  ", None) == []
