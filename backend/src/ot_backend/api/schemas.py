from __future__ import annotations

from pydantic import BaseModel


class CardMatch(BaseModel):
    name: str
    similarity: float = 1.0
    rank: int | None = None
    oracle_id: str | None = None
    scryfall_id: str | None = None


class SimilarCard(BaseModel):
    oracle_id: str
    scryfall_id: str
    name: str
    card_name: str
    similarity: float
    rank: int | None = None
    type_line: str | None = None
    mana_cost: str | None = None
    oracle_text: str | None = None
    power: str | None = None
    toughness: str | None = None
    colors: list[str] | None = None
    layout: str | None = None
    rarity: str | None = None
    legalities: dict[str, str] | None = None
    uniqueness: float | None = None
