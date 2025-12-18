from __future__ import annotations

import re
from typing import Callable, Iterable, List, Tuple


_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
_WORD_RE = re.compile(r"[a-z0-9_]+")


def strip_reminder_text(text: str) -> str:
    """Remove parenthetical reminder text, which is usually noise for search."""
    if not text:
        return ""
    return re.sub(r"\([^)]*\)", "", text)


def _emit_symbol_tokens(sym: str) -> List[str]:
    """
    Convert the inside of {..} into stable lexical tokens.

    Examples:
      W -> ["sym_w","mana","white"]
      2/W -> ["sym_2_w","mana","two","white"]
      T -> ["sym_t","tap"]
    """
    s = sym.strip().lower()
    out: List[str] = []

    # Keep a canonical token that round-trips.
    canonical = "sym_" + re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if canonical:
        out.append(canonical)

    # Add “human” tokens to match user queries.
    color_words = {"w": "white", "u": "blue", "b": "black", "r": "red", "g": "green", "c": "colorless"}
    num_words = {
        "0": "zero",
        "1": "one",
        "2": "two",
        "3": "three",
        "4": "four",
        "5": "five",
        "6": "six",
        "7": "seven",
        "8": "eight",
        "9": "nine",
        "10": "ten",
    }

    if s in color_words:
        out.extend(["mana", color_words[s]])
        return out
    if s.isdigit():
        out.extend(["mana", num_words.get(s, s)])
        return out
    if s == "t":
        out.extend(["tap"])
        return out
    if s == "q":
        out.extend(["untap"])
        return out
    if s == "e":
        out.extend(["energy", "counter"])
        return out

    # Hybrid / phyrexian / snow etc — extract components.
    parts = re.split(r"[/]+", s)
    if any(p in color_words for p in parts):
        out.append("mana")
        for p in parts:
            if p in color_words:
                out.append(color_words[p])
            elif p.isdigit():
                out.append(num_words.get(p, p))
            elif p in ("p", "phyrexian"):
                out.append("life")
    return out


def mtg_tokenize(text: str) -> List[str]:
    """
    Tokenize MTG oracle-ish text for TF-IDF:
    - strips reminder text
    - emits tokens for {symbols}
    - normalizes common patterns like +1/+1 and 2/2
    """
    if not text:
        return []

    t = strip_reminder_text(text.lower())
    t = t.replace("can’t", "cant").replace("can't", "cant")

    # Normalize P/T and counters so they survive splitting.
    t = re.sub(r"([+-]?\d+)\s*/\s*([+-]?\d+)", r"pt_\1_\2", t)
    t = re.sub(r"([+-]\d+)\s*/\s*([+-]\d+)", r"ptmod_\1_\2", t)
    t = re.sub(r"\+(\d+)\s*/\s*\+(\d+)", r"ptmod_plus\1_plus\2", t)
    t = re.sub(r"-(\d+)\s*/\s*-(\d+)", r"ptmod_minus\1_minus\2", t)

    # Expand {symbols} into tokens and remove from text (so braces don't pollute).
    tokens: List[str] = []
    for m in _SYMBOL_RE.finditer(t):
        tokens.extend(_emit_symbol_tokens(m.group(1)))
    t = _SYMBOL_RE.sub(" ", t)

    # Replace punctuation with spaces, keep underscores from our normalized tokens.
    t = re.sub(r"[^a-z0-9_]+", " ", t)
    tokens.extend(_WORD_RE.findall(t))

    # Drop very short noise, keep 'x' (important in oracle), and keep digits ("3" matters).
    return [tok for tok in tokens if len(tok) > 1 or tok == "x" or tok.isdigit()]


def mtg_analyzer(text: str) -> List[str]:
    """scikit-learn analyzer hook."""
    return mtg_tokenize(text)


def make_mtg_analyzer(ngram_range: Tuple[int, int] = (1, 1)) -> Callable[[str], List[str]]:
    """
    Return a scikit-learn-compatible analyzer(text)->tokens callable, with configurable n-grams.

    scikit-learn does not pass arguments into an analyzer callable, so we use a factory/closure.
    """

    lo, hi = ngram_range
    if lo < 1 or hi < lo:
        raise ValueError("ngram_range must satisfy 1 <= lo <= hi")

    def analyzer(text: str) -> List[str]:
        toks = mtg_tokenize(text)
        if not toks:
            return toks

        out: List[str] = []
        # Unigrams
        if lo <= 1 <= hi:
            out.extend(toks)

        # Higher n-grams (currently used for bigrams in TF-IDF)
        if hi >= 2 and len(toks) >= 2:
            for n in range(max(2, lo), hi + 1):
                if len(toks) < n:
                    break
                out.extend(
                    ["__".join(toks[i : i + n]) for i in range(len(toks) - n + 1)]
                )

        return out

    return analyzer


def join_fields(*fields: str | None) -> str:
    """Utility to join oracle-ish fields into one document string."""
    parts: List[str] = []
    for f in fields:
        if f:
            parts.append(f)
    return "\n".join(parts)


def normalize_type_line(type_line: str | None) -> str:
    if not type_line:
        return ""
    # Replace em-dash separators with space so we get tokens for both sides.
    return type_line.replace("\u2014", " ")


def iter_type_filters(card_type: str | None) -> Iterable[str]:
    if not card_type:
        return []
    return [t.strip().lower() for t in card_type.split(",") if t.strip()]


