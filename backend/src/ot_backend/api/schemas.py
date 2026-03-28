from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CardMatch(BaseModel):
    name: str
    similarity: float = 1.0
    rank: int | None = None
    oracle_id: str | None = None
    scryfall_id: str | None = None
    face_ix: int = 0
    image_side: Literal["front", "back"] = "front"


class SimilarCard(BaseModel):
    oracle_id: str
    scryfall_id: str
    face_ix: int
    image_side: Literal["front", "back"]
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
    border_color: str | None = None
    set_code: str | None = None


class SimilarCardsPage(BaseModel):
    items: list[SimilarCard]
    has_more: bool


class OracleSamplesResponse(BaseModel):
    texts: list[str]
    terms: list[str]


class ClientErrorEventIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    name: str = Field(min_length=1, max_length=120)
    stack: str | None = Field(default=None, max_length=16000)
    context: dict[str, Any] | None = None
    url: str = Field(min_length=1, max_length=4000)
    userAgent: str | None = Field(default=None, max_length=1000)
    timestamp: datetime | None = None


AnalyticsEventName = Literal[
    "search_submitted",
    "filters_changed",
    "filters_cleared",
    "load_more_requested",
    "card_opened",
]


class AnalyticsEventIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: AnalyticsEventName
    props: dict[str, Any] | None = None
    url: str = Field(min_length=1, max_length=4000)
    userAgent: str | None = Field(default=None, max_length=1000)
    timestamp: datetime | None = None


class TelemetryIngestResponse(BaseModel):
    accepted: bool = True
