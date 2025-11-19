import json
from pathlib import Path
from typing import Any, Dict, List

from .config import CARD_NAMES_JSON, CARDS_JSON


def load_cards(path: Path = CARDS_JSON) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        cards = json.load(f)
    return cards


def load_card_name_index(path: Path = CARD_NAMES_JSON) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
