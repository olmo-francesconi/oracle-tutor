from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel


class CardMatch(BaseModel):
    name: str
    similarity: float = 1.0
    rank: Optional[int] = None
    id: Optional[str] = None


class CardNameMatch(BaseModel):
    name: str
    id: str


class SimilarCard(BaseModel):
    id: str
    name: str
    card_name: str
    similarity: float
    rank: Optional[int] = None

    type_line: Optional[str] = None
    mana_cost: Optional[str] = None
    oracle_text: Optional[str] = None
    power: Optional[str] = None
    toughness: Optional[str] = None
    colors: Optional[List[str]] = None

    layout: Optional[str] = None
    rarity: Optional[str] = None
    legalities: Optional[Dict[str, str]] = None
    uniqueness: Optional[float] = None
