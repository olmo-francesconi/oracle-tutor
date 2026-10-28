"""Tests for the type-aware self-reference in normalized oracle text.

Ability embeddings are keyed by distinct normalized text, so two cards that
normalize identically share one vector and become indistinguishable at any
similarity threshold. `{T}` used to render as the generic "tap this card",
which collapsed a Forest and Llanowar Elves onto the same string — making
"a creature that taps for mana" unrepresentable no matter how the model was
trained.
"""

from __future__ import annotations

import pytest

from app.text import normalize_oracle_text


def _n(text: str, name: str, type_line: str) -> str:
    return normalize_oracle_text(text=text, card_name=name, type_line=type_line)


def test_a_mana_creature_and_a_mana_land_no_longer_collide() -> None:
    creature = _n("{T}: Add {G}.", "Llanowar Elves", "Creature — Elf Druid")
    land = _n("{T}: Add {G}.", "Forest", "Basic Land — Forest")

    assert creature == "tap this creature: Add one green mana."
    assert land == "tap this land: Add one green mana."
    assert creature != land


@pytest.mark.parametrize(
    ("type_line", "expected"),
    [
        ("Creature — Elf Druid", "tap this creature"),
        ("Basic Land — Forest", "tap this land"),
        ("Artifact", "tap this artifact"),
        ("Enchantment", "tap this enchantment"),
        ("Legendary Planeswalker — Chandra", "tap this planeswalker"),
    ],
)
def test_the_tap_symbol_follows_the_card_type(type_line: str, expected: str) -> None:
    assert _n("{T}: Add {C}.", "Whatever", type_line).startswith(expected)


def test_an_unknown_type_falls_back_to_the_generic_phrase() -> None:
    assert _n("{T}: Add {C}.", "Mystery", "").startswith("tap this card")


def test_untap_is_type_aware_too() -> None:
    assert "untap this creature" in _n("{Q}: Draw a card.", "Thing", "Creature — Bird")


def test_the_phrasing_matches_the_self_reference_used_elsewhere() -> None:
    """A card naming itself and a card tapping must agree, or the space splits."""
    text = _n("{T}: Grizzly Bears deals 1 damage to any target.", "Grizzly Bears", "Creature — Bear")

    assert text.count("this creature") == 2
    assert "this card" not in text


