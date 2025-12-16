from __future__ import annotations

import re


def strip_reminder_text(text: str) -> str:
    """Remove parenthetical reminder text, which is usually noise for search."""
    if not text:
        return ""
    return re.sub(r"\([^)]*\)", "", text)


def expand_symbols(text: str, card_name: str | None = None) -> str:
    """
    Expand MTG symbols like {T}, {W}, {2/W} into readable text.

    This is useful both for lexical search and for turning symbol-only queries into tokens.
    """
    if not text:
        return ""

    if card_name:
        text = text.replace(card_name, "this card")
        if "," in card_name:
            short_name = card_name.split(",")[0].strip()
            if len(short_name) > 2:
                text = text.replace(short_name, "this card")

    text = strip_reminder_text(text)

    # Ensure newline-separated abilities become sentence-ish for tokenization.
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    joined = ""
    for line in lines:
        if not line.endswith((".", "!", "?")):
            line += "."
        joined += line + " "
    text = joined

    # Basic mapping: keep it compact; tokenizer will do the “structured tokens” later.
    symbol_map = {
        "{T}": "tap",
        "{Q}": "untap",
        "{W}": "white mana",
        "{U}": "blue mana",
        "{B}": "black mana",
        "{R}": "red mana",
        "{G}": "green mana",
        "{C}": "colorless mana",
        "{S}": "snow mana",
        "{E}": "energy counter",
        "{X}": "x mana",
    }

    def repl(m: re.Match) -> str:
        key = m.group(0)
        if key in symbol_map:
            return f" {symbol_map[key]} "
        # generic numeric mana like {11}
        nm = re.match(r"^\{(\d+)\}$", key)
        if nm:
            return f" {nm.group(1)} mana "
        return " "

    text = re.sub(r"\{[a-zA-Z0-9/]+\}", repl, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


