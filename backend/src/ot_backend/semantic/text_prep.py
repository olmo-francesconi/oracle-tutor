"""Normalize MTG oracle text for semantic training and inference."""

from __future__ import annotations

import re

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
            if key.startswith("mana_"):
                parts.append(_number_word(1) + " " + phrase)
            elif key == "generic":
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


