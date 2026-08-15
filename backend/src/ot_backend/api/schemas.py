from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CardMatch(BaseModel):
    name: str
    card_name: str | None = None
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
    # The single ability on this card that best matched the query or seed card.
    # None only for faces with no rules text.
    matched_ability: str | None = None
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
    border_color: str | None = None
    set_code: str | None = None


class SimilarCardsPage(BaseModel):
    items: list[SimilarCard]
    has_more: bool


class OracleSamplesResponse(BaseModel):
    texts: list[str]
    terms: list[str]


class AdminAuthTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)


class AdminAuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SemanticModelSummary(BaseModel):
    id: str
    slug: str
    base_model_key: str | None = None
    base_model: str
    status: str
    is_active: bool
    embedding_dim: int
    artifact_sha256: str = ""
    artifact_size_bytes: int = 0
    created_at: datetime
    activated_at: datetime | None = None
    error_message: str | None = None


class SemanticModelDetail(SemanticModelSummary):
    config_json: dict[str, Any] | None = None
    metrics_json: dict[str, Any] | None = None
    embedding_count: int = 0


class SemanticModelArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_kind: str
    object_key: str
    sha256: str
    size_bytes: int
    content_type: str
    metadata_json: dict[str, Any] | None = None
    created_at: datetime


class SemanticDatasetSummary(BaseModel):
    id: str
    slug: str
    status: str
    augmentation_mode: str
    created_at: datetime
    source_semantic_data_version: int | None = None
    error_message: str | None = None


class SemanticDatasetDetail(SemanticDatasetSummary):
    config_json: dict[str, Any] | None = None
    metrics_json: dict[str, Any] | None = None


class SemanticDatasetArtifactSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_kind: str
    object_key: str
    sha256: str
    size_bytes: int
    content_type: str
    metadata_json: dict[str, Any] | None = None
    created_at: datetime
