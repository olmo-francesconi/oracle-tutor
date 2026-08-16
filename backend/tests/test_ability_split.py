"""Tests for oracle-text and query segmentation.

Pure functions, no database. The examples are drawn from real rows in the
catalog rather than invented, since the whole point of the keyword guard is to
behave correctly on text that already exists.
"""

from __future__ import annotations

import pytest

from ot_backend.semantic.ability_split import (
    MAX_QUERY_ABILITIES,
    split_ability_lines,
    split_query_abilities,
)

# ---------------------------------------------------------------------------
# Card text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Flying, vigilance, haste", ["Flying", "vigilance", "haste"]),
        ("First strike; banding", ["First strike", "banding"]),
        ("Flying; first strike; banding", ["Flying", "first strike", "banding"]),
        ("Double strike; bushido 2", ["Double strike", "bushido 2"]),
        # The head word carries the keyword and the rest is its argument.
        ("Protection from red; banding", ["Protection from red", "banding"]),
    ],
)
def test_keyword_lines_split_on_either_separator(text: str, expected: list[str]) -> None:
    assert split_ability_lines(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Prose with commas must survive intact.
        "Search your library for a Forest, reveal it, then shuffle.",
        # A menu of choices is ONE ability, not several: "or ward {2}" is not a
        # bare keyword, so the all-keywords guard refuses to split the line.
        "Keyword → Vigilance; ward {3}; or islandwalk.",
        "1 point each → Flash; deathtouch; reach; vigilance; or ward {2}",
        # Ability words are a flavour prefix on a single ability.
        "Landfall — Whenever a land you control enters, draw a card.",
    ],
)
def test_lines_that_must_stay_merged(text: str) -> None:
    assert split_ability_lines(text) == [text]


def test_semicolon_inside_reminder_text_does_not_split() -> None:
    """Reminder text is stripped before the split, so its punctuation is inert."""
    text = "Reconfigure {2} ({2}: Attach to target creature you control; or unattach.)"

    assert split_ability_lines(text) == [text]


def test_modal_bullets_stay_attached_to_their_parent() -> None:
    text = "Choose one —\n• Draw a card.\n• Gain 3 life."

    assert split_ability_lines(text) == [text]


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def test_query_without_a_separator_is_one_ability() -> None:
    """The pre-existing single-vector path must be unchanged."""
    assert split_query_abilities("draw a card when a creature dies") == [
        "draw a card when a creature dies"
    ]


def test_query_splits_on_the_double_slash() -> None:
    assert split_query_abilities("flying // whenever this creature attacks, draw a card") == [
        "flying",
        "whenever this creature attacks, draw a card",
    ]


@pytest.mark.parametrize("query", ["flying//trample", "flying // trample", "flying  //  trample"])
def test_separator_spacing_is_irrelevant(query: str) -> None:
    assert split_query_abilities(query) == ["flying", "trample"]


def test_query_inherits_the_keyword_comma_rule() -> None:
    """Typing a keyword list means several abilities, as on a card."""
    assert split_query_abilities("flying, vigilance") == ["flying", "vigilance"]


def test_pasted_oracle_text_segments_by_its_own_line_breaks() -> None:
    assert split_query_abilities("Flying\nWhenever this creature attacks, draw a card.") == [
        "Flying",
        "Whenever this creature attacks, draw a card.",
    ]


@pytest.mark.parametrize("query", ["", "   ", None, "//", " // // "])
def test_empty_queries_yield_no_abilities(query: str | None) -> None:
    assert split_query_abilities(query) == []


def test_blank_segments_are_dropped() -> None:
    assert split_query_abilities("flying // // trample") == ["flying", "trample"]


def test_splitter_does_not_truncate_at_the_cap() -> None:
    """The cap is the caller's to enforce — silently cutting would hide it."""
    query = " // ".join(f"ability {i}" for i in range(MAX_QUERY_ABILITIES + 3))

    assert len(split_query_abilities(query)) == MAX_QUERY_ABILITIES + 3
