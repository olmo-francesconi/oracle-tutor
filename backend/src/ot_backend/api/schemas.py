from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..semantic.train_options import (
    DEFAULT_TRAIN_AUGMENTATION_MODE,
    EPOCH_MAX,
    EPOCH_MIN,
    parse_train_augmentation_mode,
    serialize_train_augmentation_mode,
    validate_embed_batch_size,
    validate_train_batch_size,
)


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


class SemanticModelPromotionAccepted(BaseModel):
    accepted: bool = True
    job_id: str
    model_id: str
    status: str


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


class SemanticJobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: str
    status: str
    requested_by: str
    model_id: str | None = None
    dataset_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


class SemanticJobDetail(SemanticJobSummary):
    model_config = ConfigDict(from_attributes=True)

    payload_json: dict[str, Any]
    result_json: dict[str, Any] | None = None


class SemanticTrainAugmentationOption(BaseModel):
    key: str
    label: str
    description: str
    default_enabled: bool


class SemanticTrainOptions(BaseModel):
    epoch_min: int = EPOCH_MIN
    epoch_max: int = EPOCH_MAX
    batch_size_options: list[int]
    embed_batch_size_options: list[int]
    augmentation_options: list[SemanticTrainAugmentationOption]


class SemanticTrainJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1, max_length=255)
    dataset_id: str = Field(min_length=1, max_length=64)
    model_slug: str = Field(min_length=1, max_length=120)
    base_model_key: str = Field(min_length=1, max_length=120)
    skip_fine_tune: bool = False
    epochs: int = Field(default=2, ge=EPOCH_MIN, le=EPOCH_MAX)
    batch_size: int = Field(default=64)
    promote_after_register: bool = False
    embed_batch_size: int = Field(default=256)

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, value: int) -> int:
        return validate_train_batch_size(value)

    @field_validator("embed_batch_size")
    @classmethod
    def validate_embed_batch_size_value(cls, value: int) -> int:
        return validate_embed_batch_size(value)


class SemanticDatasetJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1, max_length=255)
    dataset_slug: str = Field(min_length=1, max_length=120)
    augmentation_mode: str = Field(default=DEFAULT_TRAIN_AUGMENTATION_MODE, min_length=1, max_length=120)

    @field_validator("augmentation_mode")
    @classmethod
    def validate_augmentation_mode(cls, value: str) -> str:
        return serialize_train_augmentation_mode(parse_train_augmentation_mode(value))


class SemanticPromoteJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1, max_length=255)
    model_id: str = Field(min_length=1, max_length=64)
    embed_batch_size: int = Field(default=256)

    @field_validator("embed_batch_size")
    @classmethod
    def validate_embed_batch_size_value(cls, value: int) -> int:
        return validate_embed_batch_size(value)


class SemanticModelPromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1, max_length=255)
    embed_batch_size: int = Field(default=256)

    @field_validator("embed_batch_size")
    @classmethod
    def validate_embed_batch_size_value(cls, value: int) -> int:
        return validate_embed_batch_size(value)


class SemanticBaseModelOption(BaseModel):
    key: str
    label: str
    base_model: str
    embedding_dim: int
