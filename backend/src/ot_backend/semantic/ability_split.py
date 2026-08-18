"""Split a card face's oracle text into its individual abilities.

Oracle text is authored one ability per line, with three wrinkles this module
handles:

* A line of comma- or semicolon-separated *keyword* abilities ("Flying,
  vigilance, haste", "First strike; banding") is several abilities sharing a
  line. Splitting is driven by Scryfall's keyword-ability catalog rather than a
  shape heuristic, because ordinary rules text is full of commas too ("Search
  your library for a Forest, reveal it, ...") and must stay intact.
* Modal bullet lines ("• Draw a card.") are *modes* of the ability that
  introduces them, not abilities in their own right, so they stay attached.
* Ability words ("Landfall — Whenever ...") are flavor prefixes on a single
  ability and are deliberately not split.

The catalog is baked in rather than fetched: it changes a few times a year, and
a stale entry only means a keyword line stays merged, which is harmless.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from .text_prep import EMPTY_ORACLE_TOKEN, normalize_oracle_text

# Scryfall /catalog/keyword-abilities. Keyword *actions* (sacrifice, exile, ...)
# are intentionally excluded: they appear mid-sentence in ordinary rules text,
# and including them would shred multi-clause abilities into fragments.
KEYWORD_ABILITIES: frozenset[str] = frozenset(
    {
        'absorb', 'affinity', 'afflict', 'afterlife', 'aftermath', 'amplify', 'annihilator', 'ascend',
        'assist', 'augment', 'aura swap', 'awaken', 'backup', 'banding', 'bargain', 'basic landcycling',
        'battle cry', 'bestow', 'blitz', 'bloodthirst', 'boast', 'bushido', 'buyback', 'cascade',
        'casualty', 'champion', 'changeling', 'choose a background', 'cipher', 'cleave',
        'commander ninjutsu', 'companion', 'compleated', 'conspire', 'convoke', 'craft', 'crew',
        'cumulative upkeep', 'cycling', 'dash', 'daybound', 'deathtouch', 'decayed', 'defender',
        'delve', 'demonstrate', 'desertwalk', 'dethrone', 'devoid', 'devour', 'disguise', 'disturb',
        "doctor's companion", 'double agenda', 'double strike', 'double team', 'dredge', 'echo',
        'embalm', 'emerge', 'enchant', 'encore', 'enlist', 'entwine', 'epic', 'equip', 'escalate',
        'escape', 'eternalize', 'evoke', 'evolve', 'exalted', 'exhaust', 'exploit', 'extort',
        'fabricate', 'fading', 'fear', 'firebending', 'first strike', 'flanking', 'flash', 'flashback',
        'flying', 'for mirrodin!', 'forecast', 'forestcycling', 'forestwalk', 'foretell', 'fortify',
        'freerunning', 'frenzy', 'friends forever', 'fuse', 'gift', 'graft', 'gravestorm', 'harmonize',
        'haste', 'haunt', 'hexproof', 'hexproof from', 'hidden agenda', 'hideaway', 'horsemanship',
        'impending', 'improvise', 'increment', 'indestructible', 'infect', 'ingest', 'intensity',
        'intimidate', 'islandcycling', 'islandwalk', 'job select', 'jump-start', 'kicker',
        'landcycling', 'landwalk', 'legendary landwalk', 'level up', 'lifelink', 'living metal',
        'living weapon', 'madness', 'max speed', 'mayhem', 'megamorph', 'melee', 'menace', 'mentor',
        'miracle', 'mobilize', 'modular', 'more than meets the eye', 'morph', 'mountaincycling',
        'mountainwalk', 'multikicker', 'mutate', 'myriad', 'nightbound', 'ninjutsu',
        'nonbasic landwalk', 'offering', 'offspring', 'outlast', 'overload', 'paradigm', 'partner',
        'partner with', 'persist', 'phasing', 'plainscycling', 'plainswalk', 'poisonous', 'power-up',
        'protection', 'prototype', 'provoke', 'prowess', 'prowl', 'rampage', 'ravenous', 'reach',
        'read ahead', 'rebound', 'reconfigure', 'recover', 'reinforce', 'renown', 'replicate',
        'retrace', 'riot', 'ripple', 'saddle', 'scavenge', 'shadow', 'shroud', 'skulk', 'slivercycling',
        'sneak', 'solved', 'soulbond', 'soulshift', 'specialize', 'spectacle', 'splice', 'split second',
        'spree', 'squad', 'station', 'storm', 'sunburst', 'surge', 'suspend', 'swampcycling',
        'swampwalk', 'teamwork', 'tiered', 'toxic', 'training', 'trample', 'transfigure', 'transmute',
        'tribute', 'typecycling', 'umbra armor', 'undaunted', 'undying', 'unearth', 'unleash',
        'vanishing', 'vigilance', 'ward', 'warp', 'web-slinging', 'wither', 'wizardcycling',
    }
)

_REMINDER = re.compile(r"\s*\([^)]*\)")
# Oracle joins keywords on one line with either separator: "Flying, vigilance"
# and "First strike; banding" are both two abilities. Reminder text is stripped
# before this is applied, so a semicolon inside a reminder ("{2}: Attach to
# target creature you control; or unattach...") cannot trigger a split.
_KEYWORD_LINE_SEPARATOR = re.compile(r"[;,]")
# Free-text queries use the MTG-native "separate halves" mark. Chosen over `;`,
# `|` and `&`, which all occur far more often inside real ability text.
_QUERY_SEPARATOR = re.compile(r"\s*//\s*")
# Each query ability costs one exact-kNN probe over every distinct ability
# vector, so the count is capped rather than left open.
MAX_QUERY_ABILITIES = 6
# Trailing cost or argument on a keyword: "Ward {2}", "Cycling {1}{G}", "Annihilator 2".
_KEYWORD_ARGUMENT = re.compile(r"\s*(\{[^}]*\}|[\u2014-]\s*.*|\d+)+$")
_MODAL_BULLET = "\u2022"


@dataclass(frozen=True)
class Ability:
    ability_ix: int
    text: str
    normalized_text: str
    text_hash: str
    # Bare evergreen/keyword abilities ("Flying", "Ward {2}"). Kept in the index
    # so "flying" is still searchable and keyword-only creatures still exist,
    # but flagged so callers can exclude them from scoring.
    is_keyword: bool = False


def ability_text_hash(normalized_text: str) -> str:
    """Stable dedup key. Distinct ability texts are embedded once and shared by
    every face that has them ("flying" occurs on ~3.2k faces)."""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def _is_keyword_ability(part: str) -> bool:
    candidate = part.strip().rstrip(".").lower()
    if not candidate:
        return False
    if candidate in KEYWORD_ABILITIES:
        return True
    if _KEYWORD_ARGUMENT.sub("", candidate).strip() in KEYWORD_ABILITIES:
        return True
    # "Protection from black", "Landwalk"-style variants: the head word carries
    # the keyword and the rest is its argument.
    return candidate.split(" from ")[0] in KEYWORD_ABILITIES


def split_ability_lines(oracle_text: str | None) -> list[str]:
    """Return the raw ability strings for one face, in printed order."""
    if not oracle_text or not oracle_text.strip():
        return []

    abilities: list[str] = []
    for raw_line in oracle_text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(_MODAL_BULLET) and abilities:
            abilities[-1] = abilities[-1] + "\n" + line
            continue

        without_reminder = _REMINDER.sub("", line).strip()
        parts = [part for part in _KEYWORD_LINE_SEPARATOR.split(without_reminder) if part.strip()]
        # Split only when *every* part is a keyword; one non-keyword part means
        # this is prose that happens to contain commas or semicolons.
        if len(parts) > 1 and all(_is_keyword_ability(part) for part in parts):
            abilities.extend(part.strip().rstrip(".") for part in parts)
            continue

        abilities.append(line)
    return abilities


def split_query_abilities(query: str | None) -> list[str]:
    """Segment a free-text query into abilities, exactly as card text is segmented.

    ` // ` becomes a line break and the result goes through `split_ability_lines`,
    so a query is subject to the same rules as the corpus it searches: one
    ability per line, modal bullets stay attached to their parent, and a line of
    comma- or semicolon-separated keywords ("flying, vigilance") is two
    abilities. Pasting real oracle text therefore works without extra handling.

    Returns every ability found; enforcing `MAX_QUERY_ABILITIES` is the caller's
    job, so an over-long query is rejected outright rather than quietly cut.
    """
    if not query or not query.strip():
        return []
    return split_ability_lines(_QUERY_SEPARATOR.sub("\n", query))


# Keywords whose entire effect lives in reminder text we strip: "Cycling {2}"
# normalizes to "Cycling two generic mana", so nobody searching "discard this
# card to draw a card" can find a cycler. The expansion is applied to EVERY
# printing of a head shape, not only the ones that print the reminder — 907 of
# 1,228 Equip printings omit it, so a printing-dependent rule would split one
# concept into two vectors.
#
# Evergreen bare keywords are deliberately absent from the catalog: expanding
# "Flying" drops its self-match against the query "flying" from 1.000 to 0.479,
# below the ~0.70 floor that short ability text already sits above.
_COST_RUN = re.compile(r"(?:\{[^}]*\})+")


@lru_cache(maxsize=1)
def _keyword_expansions() -> dict[str, str]:
    raw = files("ot_backend.semantic").joinpath("keyword_expansions.json").read_bytes()
    return {str(k): str(v) for k, v in json.loads(raw)["expansions"].items()}


def _expanded_source(line: str) -> str | None:
    """The text to embed for a catalogued keyword, or None to leave it alone."""
    head = _REMINDER.sub("", line).strip().rstrip(".").strip()
    if not head:
        return None
    template = _keyword_expansions().get(_COST_RUN.sub("{cost}", head))
    if template is None:
        return None
    costs = _COST_RUN.findall(head)
    expansion = template.replace("{cost}", costs[0]) if costs else template
    # The keyword itself is kept so "cycling" stays searchable by name.
    return f"{head}. {expansion}"


# Overload changes the printed text rather than adding to it: "change 'target'
# in its text to 'each'". The overloaded mode is the reason these cards see play
# — Cyclonic Rift is a staple as a one-sided board wipe, not as a 7-mana
# Disperse — and it appears nowhere in the corpus, because reminder text is
# stripped. So the mode is emitted as its own ability.
_OVERLOAD_PREFIX = "Overloaded"
_TARGET_WORD = re.compile(r"\btarget\b", re.IGNORECASE)
_SENTENCE_START = re.compile(r"(^|[.!?]\s+|\n)(target)\b", re.IGNORECASE)


def _overloaded_text(text: str) -> str:
    """Apply overload's substitution, keeping sentence capitalisation."""
    rewritten = _SENTENCE_START.sub(lambda m: f"{m.group(1)}Each", text)
    return _TARGET_WORD.sub("each", rewritten)


def _ability_sources(oracle_text: str | None) -> list[tuple[str, str]]:
    """(display text, text to embed) per ability.

    The two differ only where we synthesise an ability the card does not print:
    the display carries a marker so the tuner does not appear to invent card
    text, while the embedded side stays clean so the marker never reaches a
    vector.
    """
    lines = split_ability_lines(oracle_text)
    sources = [(line, _expanded_source(line) or line) for line in lines]

    overload_at = next(
        (i for i, line in enumerate(lines) if _REMINDER.sub("", line).strip().lower().startswith("overload")),
        None,
    )
    if overload_at is None:
        return sources
    targeted = [i for i, line in enumerate(lines) if i != overload_at and _TARGET_WORD.search(line)]
    # Every overload card in the corpus has exactly one targeted ability. More
    # than one and the substitution is ambiguous, so leave the card alone rather
    # than guess which mode the overload cost applies to.
    if len(targeted) != 1:
        return sources
    base = lines[targeted[0]]
    rewritten = _overloaded_text(_REMINDER.sub("", base).strip())
    sources.insert(targeted[0] + 1, (f"{_OVERLOAD_PREFIX} \u2014 {rewritten}", rewritten))
    return sources


def build_face_abilities(
    *,
    oracle_text: str | None,
    card_name: str = "",
    type_line: str = "",
) -> list[Ability]:
    """Segment and normalize one face's oracle text into embeddable abilities.

    Faces with no rules text (vanilla creatures) still get a single
    placeholder ability so they remain represented in the index.
    """
    abilities: list[Ability] = []
    seen_hashes: set[str] = set()
    for text, source in _ability_sources(oracle_text):
        normalized = normalize_oracle_text(text=source, card_name=card_name, type_line=type_line)
        # A line that was pure reminder text normalizes away to nothing.
        if normalized == EMPTY_ORACLE_TOKEN:
            continue
        text_hash = ability_text_hash(normalized)
        # Some cards print a keyword twice ("Flying, vigilance, prowess, prowess").
        # Keep one copy so a repeated keyword doesn't get extra weight when
        # ability sets are averaged during scoring.
        if text_hash in seen_hashes:
            continue
        seen_hashes.add(text_hash)
        abilities.append(
            Ability(
                ability_ix=len(abilities),
                text=text,
                normalized_text=normalized,
                text_hash=text_hash,
                is_keyword=_is_keyword_ability(_REMINDER.sub("", text)),
            )
        )

    if not abilities:
        return [
            Ability(
                ability_ix=0,
                text="",
                normalized_text=EMPTY_ORACLE_TOKEN,
                text_hash=ability_text_hash(EMPTY_ORACLE_TOKEN),
            )
        ]
    return abilities
