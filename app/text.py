"""Oracle text -> abilities: segmentation, normalization and the text_hash dedup key.

Ported verbatim from v2 (semantic/text_prep.py + semantic/ability_split.py): the
text_hash values and ability_ix numbering must not drift, since ability_ix
appears in shared URLs (inc/exc)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

EMPTY_ORACLE_TOKEN = "emptyoracle"

_LOYALTY_PATTERN = re.compile(r"([+-])\s*(\d+)\s*(:)?")
_PT_PATTERN = re.compile(r"([+-])?\s*(\d+|[XYZ])\s*/\s*([+-])?\s*(\d+|[XYZ])", re.IGNORECASE)
_ALLOWED_CHARS = re.compile(r"[^a-zA-Z0-9\s.,/+\-:]")

_NUMBER_WORDS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "twenty-one",
    "twenty-two",
    "twenty-three",
    "twenty-four",
    "twenty-five",
]

_BASIC_LAND_TYPES = frozenset({"plains", "island", "swamp", "mountain", "forest"})


def _number_word(n: int) -> str:
    if 0 <= n < len(_NUMBER_WORDS):
        return _NUMBER_WORDS[n]
    return str(n)


# Scryfall retemplated roughly half the corpus to refer to a card as
# "this creature" / "this artifact" / "this spell". For the ~12% of faces that
# still print their own name we do the substitution ourselves, and we must use
# the SAME phrasing — writing "this card" there would split the vector space,
# embedding "this card deals 4 damage" away from the identical-in-meaning
# "this creature deals 4 damage".
#
# Ordered by Scryfall's own precedence: an Artifact Creature is "this creature",
# an Artifact Land is "this land".
_SELF_REFERENCE_BY_TYPE: tuple[tuple[str, str], ...] = (
    ("creature", "this creature"),
    ("planeswalker", "this planeswalker"),
    ("land", "this land"),
    ("artifact", "this artifact"),
    ("enchantment", "this enchantment"),
    ("instant", "this spell"),
    ("sorcery", "this spell"),
)
_DEFAULT_SELF_REFERENCE = "this card"


def self_reference_phrase(type_line: str | None) -> str:
    """How Scryfall would refer to a card of this type in its own rules text."""
    if not type_line:
        return _DEFAULT_SELF_REFERENCE
    # Primary types are always left of the em dash; subtypes on the right can
    # collide ("Creature — Elf Assassin" vs an "Assassin" artifact subtype).
    primary = type_line.split("—", 1)[0].lower()
    tokens = {token for token in primary.replace("//", " ").split() if token}
    for type_name, phrase in _SELF_REFERENCE_BY_TYPE:
        if type_name in tokens:
            return phrase
    return _DEFAULT_SELF_REFERENCE


def has_basic_land_type(type_line: str | None) -> bool:
    if not type_line or not type_line.strip():
        return False
    lower = type_line.strip().lower()
    if "land" not in lower:
        return False
    return any(t in lower for t in _BASIC_LAND_TYPES)


def strip_reminder_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\(([^)]*)\)", r" \1 ", text)


def _strip_reminder_text_fully(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\([^)]*\)", " ", text)


def _replace_card_name_standalone(text: str, name: str, replacement: str) -> str:
    if not name:
        return text
    escaped = re.escape(name)
    before = r"(^|[\s.,;:!?()\[\]\-])"
    after = r"($|[\s.,;:!?()\[\]\-])"
    pattern = before + escaped + after
    return re.sub(pattern, r"\1" + replacement + r"\2", text)


def _parse_symbol(inner: str, self_reference: str = _DEFAULT_SELF_REFERENCE) -> tuple[str, str, bool, int] | None:
    s = inner.strip().upper()
    if not s:
        return None
    if s == "T":
        # Type-aware, like every other self-reference in this module. Rendering
        # {T} as the generic "tap this card" made a Forest and Llanowar Elves
        # normalise to byte-identical text, so they shared one embedding and no
        # amount of training could tell a mana creature from a mana land.
        return ("tap", f"tap {self_reference}", True, 1)
    if s == "Q":
        return ("untap", f"untap {self_reference}", True, 1)
    color_map = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
    if s in color_map:
        return ("mana_" + s, color_map[s] + " mana", True, 1)
    if s == "C":
        return ("mana_C", "colorless mana", True, 1)
    if s == "S":
        return ("mana_S", "snow mana", True, 1)
    if s == "E":
        return ("energy", "energy counter", True, 1)
    if s == "X":
        return ("x", "x mana", False, 1)
    if s.isdigit():
        n = int(s)
        return ("generic", "generic mana", True, n)

    parts = re.split(r"[/]+", s)
    if len(parts) >= 2:
        bits = []
        for p in parts:
            p = p.strip()
            if p in color_map:
                bits.append(color_map[p])
            elif p.isdigit():
                bits.append(_number_word(int(p)))
            elif p in ("P", "PHYREXIAN"):
                bits.append("phyrexian")
            else:
                bits.append(p.lower())
        phrase = " or ".join(bits) + " mana"
        return ("hybrid", phrase, False, 1)
    return None


def _expand_symbol_run(symbols: list[str], self_reference: str = _DEFAULT_SELF_REFERENCE) -> str:
    if not symbols:
        return ""
    parsed: list[tuple[str, str, bool, int]] = []
    for sym in symbols:
        inner = sym.strip().upper()
        if inner.startswith("{") and inner.endswith("}"):
            inner = inner[1:-1]
        p = _parse_symbol(inner, self_reference)
        if p is None:
            continue
        parsed.append(p)
    if not parsed:
        return ""

    groups: list[tuple[str, str, bool, int]] = []
    for key, phrase, countable, amt in parsed:
        if groups and groups[-1][0] == key:
            prev = groups[-1]
            groups[-1] = (key, phrase, countable, prev[3] + amt)
        else:
            groups.append((key, phrase, countable, amt))

    parts = []
    for key, phrase, countable, n in groups:
        if n == 1:
            if key.startswith("mana_") or key == "generic":
                parts.append(_number_word(1) + " " + phrase)
            else:
                parts.append(phrase)
        elif countable:
            if "counter" in phrase:
                base = phrase.replace(" counter", "")
                parts.append(_number_word(n) + " " + base + " counters")
            elif key == "generic" or key.startswith("mana_") or "mana" in phrase:
                parts.append(_number_word(n) + " " + phrase)
            else:
                if n == 2:
                    parts.append(phrase + " twice")
                else:
                    parts.append(phrase + " " + _number_word(n) + " times")
        else:
            parts.append(phrase)
    return " and ".join(parts)


def _replace_symbol_runs(text: str, self_reference: str = _DEFAULT_SELF_REFERENCE) -> str:
    pattern = re.compile(r"(\{[a-zA-Z0-9/]+\})+")

    def replace_run(m: re.Match[str]) -> str:
        symbols = re.findall(r"\{([^}]+)\}", m.group(0))
        expanded = _expand_symbol_run(symbols, self_reference)
        return " " + expanded + " " if expanded else " "

    return pattern.sub(replace_run, text)


def _normalize_planeswalker_loyalty(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        sign, num, colon = m.groups()
        n = int(num)
        word = _number_word(n)
        action = ("add " if sign == "+" else "remove ") + word
        action += " loyalty counter" if n == 1 else " loyalty counters"
        return action + (" :" if colon else "")

    return _LOYALTY_PATTERN.sub(repl, text)


def _is_pt_variable(s: str) -> bool:
    return len(s) == 1 and s.upper() in ("X", "Y", "Z")


def _normalize_power_toughness(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        p_sign, p_val_str, t_sign, t_val_str = m.groups()
        # None means no explicit sign (e.g. token "1/1" → "one strength and one toughness").
        # An explicit "+" or "-" means a modifier (e.g. "+1/+1 counter" or "-1/-1 counter").
        p_prefix = ("plus " if p_sign == "+" else "minus ") if p_sign else ""
        t_prefix = ("plus " if t_sign == "+" else "minus ") if t_sign else ""
        parts = []
        if _is_pt_variable(p_val_str):
            parts.append(f"{p_prefix}{p_val_str.lower()} power")
        else:
            p_val = int(p_val_str)
            if p_val != 0:
                parts.append(f"{p_prefix}{_number_word(p_val)} strength")
        if _is_pt_variable(t_val_str):
            parts.append(f"{t_prefix}{t_val_str.lower()} toughness")
        else:
            t_val = int(t_val_str)
            if t_val != 0:
                parts.append(f"{t_prefix}{_number_word(t_val)} toughness")
        if not parts:
            return " "
        return " " + " and ".join(parts) + " "

    return _PT_PATTERN.sub(repl, text)


def _numerals_to_words(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        return _number_word(int(m.group(0)))

    return re.sub(r"\d+", repl, text)


def _strip_disallowed_symbols(text: str) -> str:
    text = text.replace("'", "")
    text = _ALLOWED_CHARS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_punctuation_spacing(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+([.,/+\-:])", r"\1", text)
    text = re.sub(r"([.,/+\-:])\s*\1+", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_mana_cost(clause: str) -> bool:
    return "mana" in clause.strip().lower()


def _add_pay_before_mana_costs(text: str) -> str:
    phrases = re.split(r"\.\s+", text)
    out = []
    for phrase in phrases:
        idx = phrase.find(" :")
        if idx == -1:
            idx = phrase.find(":")
        if idx == -1:
            out.append(phrase)
            continue
        cost = phrase[:idx].strip().replace(",", " and ")
        rest = phrase[idx:]
        phrase = cost + rest
        if _looks_like_mana_cost(cost) and not cost.lower().startswith("pay "):
            phrase = "pay " + cost + rest
        out.append(phrase)
    return ". ".join(p.strip() for p in out if p.strip()).strip()


def normalize_oracle_text(
    text: str | None,
    card_name: str = "",
    type_line: str = "",
    keep_reminder_text: bool = False,
) -> str:
    if not text:
        return EMPTY_ORACLE_TOKEN

    if keep_reminder_text or has_basic_land_type(type_line):
        text = strip_reminder_text(text)
    else:
        text = _strip_reminder_text_fully(text)

    self_reference = self_reference_phrase(type_line)
    if card_name:
        text = _replace_card_name_standalone(text, card_name, self_reference)
        if "," in card_name:
            short_name = card_name.split(",")[0].strip()
            if len(short_name) > 2 and short_name != card_name:
                text = _replace_card_name_standalone(text, short_name, self_reference)

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    joined = ""
    for line in lines:
        if not line.endswith((".", "!", "?")):
            line += "."
        joined += line + " "
    text = joined

    text = _replace_symbol_runs(text, self_reference)
    text = re.sub(r"\s+", " ", text).strip()
    text = _normalize_power_toughness(text)
    text = _normalize_planeswalker_loyalty(text)
    text = _add_pay_before_mana_costs(text)
    text = _numerals_to_words(text)
    text = _strip_disallowed_symbols(text)
    text = _normalize_punctuation_spacing(text)
    return text or EMPTY_ORACLE_TOKEN



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
    raw = (Path(__file__).parent / "keyword_expansions.json").read_bytes()
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
