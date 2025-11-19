from typing import List

COLOR_MAP = {
    "white": "w",
    "blue": "u",
    "black": "b",
    "red": "r",
    "green": "g",
}


def build_basic_filters(text: str) -> List[str]:
    text_l = text.lower()
    filters: List[str] = []

    # Example: very basic color parsing
    colors = [sym for name, sym in COLOR_MAP.items() if name in text_l]
    if colors:
        if "mono" in text_l or "monocolor" in text_l:
            if len(colors) == 1:
                filters.append(f"id={colors[0]}")  # mono-color
        else:
            colors_sorted = "".join(sorted(colors))
            filters.append(f"id>={colors_sorted}")  # includes at least those

    # Types
    if "creature" in text_l:
        filters.append("t:creature")

    return filters
