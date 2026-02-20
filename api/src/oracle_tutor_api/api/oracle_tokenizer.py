from __future__ import annotations

import re
import unicodedata
from typing import Callable, Iterable, List, Tuple


_WORD_RE = re.compile(r"[a-z0-9_]+")

# Symbol mapping constants
_COLOR_WORDS = {"w": "white", "u": "blue", "b": "black", "r": "red", "g": "green", "c": "colorless"}
_NUM_WORDS = {
    str(i): name
    for i, name in enumerate(
        ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
    )
}
_NUM_WORDS.update({"100": "one hundred", "1000000": "one million", "x": "x", "y": "y", "z": "z"})


def strip_reminder_text(text: str) -> str:
    """Remove parenthetical reminder text, which is usually noise for search."""
    if not text:
        return ""
    return re.sub(r"\([^)]*\)", "", text)


def _get_number_word(count: int | str) -> str:
    """Convert number or 'x/y/z' to word."""
    return _NUM_WORDS.get(str(count).lower().strip(), str(count))


def _resolve_single_symbol(symbol: str) -> str:
    """Map single symbol to semantic text. Returns empty string for unknown symbols."""
    s = symbol.strip().lower()

    if s in _COLOR_WORDS:
        return f"{_COLOR_WORDS[s]} mana"
    
    # Generic / Variables
    if s.isdigit() or s in ("x", "y", "z"):
        return f"{_get_number_word(s)} mana"
    
    # Simple mappings
    mapping = {
        "t": "tap", 
        "q": "untap", 
        "e": "energy counter",
        "s": "snow mana",
        "c": "colorless mana",
        "pw": "planeswalker",
        "chaos": "chaos symbol",
        "tk": "ticket counter",
        "a": "acorn symbol",
        "i": "chapter one",
        "ii": "chapter two",
        "iii": "chapter three",
        "iv": "chapter four",
        "v": "chapter five",
        "∞": "infinity mana"
    }
    if s in mapping:
        return mapping[s]

    # Half mana
    if s.startswith("h") and s[1:] in _COLOR_WORDS:
        return f"half {_COLOR_WORDS[s[1:]]} mana"

    # Hybrid / Phyrexian / Multi-part
    parts = re.split(r"/+", s)
    if len(parts) > 1:
        is_phyrexian = "p" in parts
        # Filter out 'p' for the color-joining logic
        clean_parts = [p for p in parts if p != "p"]
        
        semantic_parts = []
        for p in clean_parts:
            if p in _COLOR_WORDS:
                semantic_parts.append(_COLOR_WORDS[p])
            elif p.isdigit() or p in ("x", "y", "z"):
                semantic_parts.append(_get_number_word(p))
        
        if semantic_parts:
            base = " or ".join(semantic_parts)
            if is_phyrexian:
                return f"phyrexian {base} mana"
            return f"{base} mana"

    return ""  # Unknown symbol


def _count_consecutive_symbols(text: str, start_pos: int) -> Tuple[int, str]:
    """Count consecutive identical symbols starting at position. Returns (count, symbol_text)."""
    if not text or start_pos >= len(text) or text[start_pos] != "{":
        return 0, ""
    
    end_pos = text.find("}", start_pos)
    if end_pos == -1:
        return 0, ""
    
    symbol = text[start_pos : end_pos + 1]
    count = 0
    pos = start_pos
    
    while text.startswith(symbol, pos):
        count += 1
        pos += len(symbol)
    
    return count, symbol


def substitute_card_name(text: str, card_name: str | None) -> str:
    """Replace card name with 'this card'. Handles comma-separated names (legends)."""
    if not text or not card_name:
        return text
    
    # Replace full card name
    text = re.sub(re.escape(card_name), "this card", text, flags=re.IGNORECASE)
    
    # For legends, replace the shorthand name (everything before the first comma)
    if "," in card_name:
        short_name = card_name.split(",")[0].strip()
        if len(short_name) > 2:
            text = re.sub(rf"\b{re.escape(short_name)}\b", "this card", text, flags=re.IGNORECASE)
    
    return text


def normalize_text(text: str) -> str:
    """Normalize text: lowercase, remove accents, remove apostrophes."""
    if not text:
        return ""
    
    # Convert to lowercase
    text = text.lower()
    
    # Remove accents and normalize unicode
    # Use NFKD normalization to decompose characters, then remove combining marks
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    
    # Remove all types of apostrophes/quotes
    text = re.sub(r"['\u2018\u2019\u201a\u201b]", "", text)
    
    # Normalize other common unicode characters
    text = text.replace("—", "-").replace("–", "-")  # Em/en dashes to hyphen
    text = text.replace("…", "...")  # Ellipsis
    
    return text


def resolve_symbols_inplace(text: str) -> str:
    """Resolve symbols in-place to semantic text. Handles consecutive identical symbols."""
    if "{" not in text:
        return text

    result = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            count, symbol_text = _count_consecutive_symbols(text, i)
            if count > 0:
                symbol_content = symbol_text[1:-1]
                semantic = _resolve_single_symbol(symbol_content)
                if semantic:
                    if count > 1:
                        number_word = _get_number_word(count)
                        if semantic.endswith(" mana"):
                            resolved = f" {number_word} {semantic} "
                        elif semantic.endswith(" counter"):
                            resolved = f" {number_word} {semantic}s "
                        else:
                            resolved = f" {number_word} {semantic} "
                    else:
                        resolved = f" {semantic} "
                    
                    result.append(resolved)
                    i += count * len(symbol_text)
                    continue
        
        result.append(text[i])
        i += 1
    return "".join(result)


def split_into_phrases(text: str) -> List[str]:
    """Split text into phrases on line breaks and periods. Filter out empty phrases."""
    if not text:
        return []
    
    # Split on both line breaks and periods
    phrases = re.split(r"[\n.]+", text)
    
    # Clean up each phrase and filter empty ones
    cleaned = [phrase.strip() for phrase in phrases if phrase.strip()]
    
    return cleaned


def tokenize_phrase(phrase: str) -> List[str]:
    """Tokenize a single phrase into words. Handles P/T patterns and extracts word tokens."""
    if not phrase:
        return []
    
    # Normalize P/T patterns (e.g., +1/+1, 2/2, +X/+X)
    def pt_replacer(match: re.Match) -> str:
        v1, v2 = match.groups()
        
        def resolve_val(v: str) -> str:
            res = []
            if v.startswith("+"):
                res.append("plus")
                num = v[1:]
            elif v.startswith("-"):
                res.append("minus")
                num = v[1:]
            else:
                num = v
            
            # Use _get_number_word for the number part (handles digits and 'x')
            word = _get_number_word(num.lower())
            res.append(word)
            return " ".join(res)

        # Return space-separated words to allow n-gram analysis to pick up the semantic meaning
        return f" {resolve_val(v1)} {resolve_val(v2)} "

    # Support digits, X/x, and signs in P/T patterns
    t = re.sub(r"([+-]?[0-9xX]+)\s*/\s*([+-]?[0-9xX]+)", pt_replacer, phrase)
    
    # Replace punctuation with spaces, keep underscores from normalized tokens
    t = re.sub(r"[^a-z0-9_]+", " ", t)
    
    # Extract word tokens
    tokens = _WORD_RE.findall(t)
    
    # Filter short tokens (keep 'x' and digits)
    return [tok for tok in tokens if len(tok) > 1 or tok == "x" or tok.isdigit()]


# Special delimiter to separate card_name from oracle_text in analyzer input
_CARD_NAME_DELIMITER = "\x00\x01CARD_NAME\x01\x00"
# Special delimiter to separate type_line from oracle_text/card_name in analyzer input
_TYPE_LINE_DELIMITER = "\x00\x01TYPE_LINE\x01\x00"

BASIC_LAND_TYPE_TO_MANA = {
    "Plains": "{W}",
    "Island": "{U}",
    "Swamp": "{B}",
    "Mountain": "{R}",
    "Forest": "{G}",
}


def _generate_mana_ability(type_line: str) -> str | None:
    """
    Generate implicit mana ability for basic land types.
    e.g. "Basic Land — Plains" -> "{T}: Add {W}."
    """
    if not type_line:
        return None

    tokens = type_line.replace("—", " ").replace("-", " ").split()

    found_types = []
    seen_types = set()

    for token in tokens:
        if token in BASIC_LAND_TYPE_TO_MANA and token not in seen_types:
            found_types.append(token)
            seen_types.add(token)

    if not found_types:
        return None

    mana_symbols = [BASIC_LAND_TYPE_TO_MANA[t] for t in found_types]

    if len(mana_symbols) == 1:
        return f"{{T}}: Add {mana_symbols[0]}."
    elif len(mana_symbols) == 2:
        return f"{{T}}: Add {mana_symbols[0]} or {mana_symbols[1]}."
    else:
        joined = ", ".join(mana_symbols[:-1])
        return f"{{T}}: Add {joined}, or {mana_symbols[-1]}."


_NO_ORACLE_TEXT_TOKEN = "__no_oracle_text__"


def _tokenize_internal(text: str, card_name: str | None = None, type_line: str | None = None) -> List[List[str]]:
    """Internal core tokenization workflow without n-gram generation. Returns tokens grouped by phrase."""
    
    # 1. Strip reminder text first (so we don't duplicate ability if it was only in reminder text)
    t = strip_reminder_text(text or "")

    # 2. Inject implicit mana ability if applicable
    if type_line:
        mana_ability = _generate_mana_ability(type_line)
        if mana_ability:
            t = f"{t}\n{mana_ability}"

    # 3. Sentinel for textless cards: if still empty after stripping reminder
    #    text and injecting implicit abilities, emit a shared token so all
    #    vanilla / textless faces are seen as similar to each other.
    if not t.strip():
        t = _NO_ORACLE_TEXT_TOKEN

    # 4. Standard processing
    t = substitute_card_name(t, card_name)
    t = normalize_text(t)
    
    phrases = split_into_phrases(t)
    all_phrase_tokens: List[List[str]] = []
    
    for phrase in phrases:
        phrase_with_symbols = resolve_symbols_inplace(phrase)
        phrase_tokens = tokenize_phrase(phrase_with_symbols)
        if phrase_tokens:
            all_phrase_tokens.append(phrase_tokens)
            
    return all_phrase_tokens


def mtg_tokenize(text: str, card_name: str | None = None, type_line: str | None = None) -> List[str]:
    """Tokenize MTG oracle-ish text for TF-IDF."""
    phrase_tokens_list = _tokenize_internal(text, card_name, type_line)
    return [tok for phrase_tokens in phrase_tokens_list for tok in phrase_tokens]


def make_mtg_analyzer(ngram_range: Tuple[int, int] = (1, 1)) -> Callable[[str], List[str]]:
    """
    Return a scikit-learn-compatible analyzer(text)->tokens callable, with configurable n-grams.
    
    The analyzer expects input in the format: "oracle_text{CARD_NAME_DELIMITER}card_name{TYPE_LINE_DELIMITER}type_line"
    """
    lo, hi = ngram_range
    if lo < 1 or hi < lo:
        raise ValueError("ngram_range must satisfy 1 <= lo <= hi")

    def analyzer(text: str) -> List[str]:
        card_name: str | None = None
        type_line: str | None = None

        # Parse type_line first (it's appended last)
        if _TYPE_LINE_DELIMITER in text:
            parts = text.split(_TYPE_LINE_DELIMITER, 1)
            text = parts[0]
            if len(parts) > 1:
                type_line = parts[1] or None

        # Parse card_name
        if _CARD_NAME_DELIMITER in text:
            parts = text.split(_CARD_NAME_DELIMITER, 1)
            text = parts[0]
            if len(parts) > 1:
                card_name = parts[1] or None
        
        phrase_tokens_list = _tokenize_internal(text, card_name, type_line)
        all_tokens: List[str] = []
        
        for phrase_tokens in phrase_tokens_list:
            # Unigrams
            if lo <= 1 <= hi:
                all_tokens.extend(phrase_tokens)
            
            # Higher n-grams
            if hi >= 2:
                for n in range(max(2, lo), hi + 1):
                    if len(phrase_tokens) >= n:
                        all_tokens.extend(
                            ["__".join(phrase_tokens[i : i + n]) for i in range(len(phrase_tokens) - n + 1)]
                        )
        
        return all_tokens

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


