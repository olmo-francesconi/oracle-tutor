import json
from pathlib import Path
from typing import Any, Dict, List

from .config import CARD_NAMES_JSON, CARDS_JSON


def load_cards(path: Path = CARDS_JSON) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        cards = json.load(f)
    return cards


def build_card_name_list(cards) -> List[str]:
    # Extract English names; adjust as needed for your dataset
    names = []
    for c in cards:
        name = c.get("name")
        if name:
            names.append(name)
    return names


def build_card_lookup_by_name(cards) -> Dict[str, Dict[str, Any]]:
    return {c["name"]: c for c in cards if "name" in c}


def build_card_lookup_by_id(cards) -> Dict[str, Dict[str, Any]]:
    return {c["id"]: c for c in cards if "id" in c}


def load_card_name_index(path: Path = CARD_NAMES_JSON) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
