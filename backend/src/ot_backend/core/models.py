from __future__ import annotations

import datetime
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

SEMANTIC_EMBEDDING_DIMENSION = 384


def _semantic_embedding_type():
    return Vector(SEMANTIC_EMBEDDING_DIMENSION)


def utcnow_naive() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _uuid_str() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Metadata / ingestion tables
# ---------------------------------------------------------------------------


class SystemMetadata(Base):
    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    updated_at: Mapped[str] = mapped_column(String)
    last_ingestion: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow_naive)
    version: Mapped[str | None] = mapped_column(String, default="0.0")


class IngestionLog(Base):
    __tablename__ = "ingestion_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow_naive)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String)  # started/success/failed
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[str] = mapped_column(String)
    trigger_type: Mapped[str | None] = mapped_column(String, nullable=True)


class CardRaw(Base):
    __tablename__ = "cards_raw"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    oracle_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String)
    lang: Mapped[str] = mapped_column(String)
    layout: Mapped[str] = mapped_column(String)
    cmc: Mapped[float | None] = mapped_column(Float, nullable=True)
    mana_cost: Mapped[str | None] = mapped_column(String, nullable=True)
    type_line: Mapped[str | None] = mapped_column(String, nullable=True)
    oracle_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    colors: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    color_identity: Mapped[list[str]] = mapped_column(JSONB)
    color_indicator: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSONB)
    legalities: Mapped[dict[str, str]] = mapped_column(JSONB)
    power: Mapped[str | None] = mapped_column(String, nullable=True)
    toughness: Mapped[str | None] = mapped_column(String, nullable=True)
    loyalty: Mapped[str | None] = mapped_column(String, nullable=True)
    defense: Mapped[str | None] = mapped_column(String, nullable=True)
    rarity: Mapped[str] = mapped_column(String)
    set_code: Mapped[str] = mapped_column(String, index=True)
    set_id: Mapped[str] = mapped_column(String)
    set_name: Mapped[str] = mapped_column(String)
    set_type: Mapped[str] = mapped_column(String)
    collector_number: Mapped[str] = mapped_column(String)
    released_at: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    artist: Mapped[str | None] = mapped_column(String, nullable=True)
    illustration_id: Mapped[str | None] = mapped_column(String, nullable=True)
    image_status: Mapped[str | None] = mapped_column(String, nullable=True)
    image_uris: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    card_faces_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    all_parts: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    games: Mapped[list[str]] = mapped_column(JSONB)
    finishes: Mapped[list[str]] = mapped_column(JSONB)
    digital: Mapped[bool] = mapped_column(Boolean, default=False)
    booster: Mapped[bool] = mapped_column(Boolean, default=False)
    promo: Mapped[bool] = mapped_column(Boolean, default=False)
    promo_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    reprint: Mapped[bool] = mapped_column(Boolean, default=False)
    variation: Mapped[bool] = mapped_column(Boolean, default=False)
    variation_of: Mapped[str | None] = mapped_column(String, nullable=True)
    full_art: Mapped[bool] = mapped_column(Boolean, default=False)
    textless: Mapped[bool] = mapped_column(Boolean, default=False)
    story_spotlight: Mapped[bool] = mapped_column(Boolean, default=False)
    border_color: Mapped[str | None] = mapped_column(String, nullable=True)
    frame: Mapped[str | None] = mapped_column(String, nullable=True)
    frame_effects: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    watermark: Mapped[str | None] = mapped_column(String, nullable=True)
    edhrec_rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    prices: Mapped[dict[str, str | None] | None] = mapped_column(JSONB, nullable=True)
    arena_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mtgo_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tcgplayer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cardmarket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    multiverse_ids: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    flavor_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    flavor_name: Mapped[str | None] = mapped_column(String, nullable=True)
    content_warning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ingested_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow_naive)

    card: Mapped["Card | None"] = relationship(back_populates="raw_printing")


# ---------------------------------------------------------------------------
# Card hierarchy
# ---------------------------------------------------------------------------


class Card(Base):
    __tablename__ = "cards"

    oracle_id: Mapped[str] = mapped_column(String, primary_key=True)
    # RESTRICT (not the implicit NO ACTION) makes the invariant explicit: a
    # cards row's best-printing pointer must always reference a kept cards_raw
    # row. Ingest already orders writes so this holds (Card pointer is updated /
    # the Card is deleted before its obsolete raw printing is pruned); the DB
    # constraint loudly rejects any future code that breaks that ordering.
    scryfall_id: Mapped[str] = mapped_column(ForeignKey("cards_raw.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String, index=True)
    layout: Mapped[str | None] = mapped_column(String, nullable=True)
    cmc: Mapped[float | None] = mapped_column(Float, nullable=True)
    color_identity: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    legalities: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    edhrec_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rarity: Mapped[str | None] = mapped_column(String, nullable=True)

    raw_printing: Mapped["CardRaw"] = relationship(back_populates="card")
    faces: Mapped[list["CardFace"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    taggings: Mapped[list["CardTagging"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    relationships: Mapped[list["CardRelationship"]] = relationship(back_populates="card", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, object]:
        return {
            "oracle_id": self.oracle_id,
            "scryfall_id": self.scryfall_id,
            "name": self.name,
            "layout": self.layout,
            "cmc": self.cmc,
            "edhrec_rank": self.edhrec_rank,
            "rarity": self.rarity,
            "legalities": self.legalities,
            "set_code": self.raw_printing.set_code if self.raw_printing else None,
            "border_color": self.raw_printing.border_color if self.raw_printing else None,
            "faces": [f.to_dict() for f in self.faces],
        }


class CardFace(Base):
    __tablename__ = "card_faces"
    __table_args__ = (
        ForeignKeyConstraint(["oracle_id"], ["cards.oracle_id"], ondelete="CASCADE"),
    )

    oracle_id: Mapped[str] = mapped_column(String, primary_key=True)
    face_ix: Mapped[int] = mapped_column(Integer, primary_key=True)
    scryfall_face_oracle_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    mana_cost: Mapped[str | None] = mapped_column(String, nullable=True)
    type_line: Mapped[str | None] = mapped_column(String, nullable=True)
    oracle_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    power: Mapped[str | None] = mapped_column(String, nullable=True)
    toughness: Mapped[str | None] = mapped_column(String, nullable=True)
    loyalty: Mapped[str | None] = mapped_column(String, nullable=True)
    defense: Mapped[str | None] = mapped_column(String, nullable=True)
    colors: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    color_indicator: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Normalized primary card types extracted from type_line. GIN-indexed
    # native ARRAY column for fast overlap filters.
    type_categories: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    image_uris: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    artist: Mapped[str | None] = mapped_column(String, nullable=True)
    flavor_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cmc: Mapped[float | None] = mapped_column(Float, nullable=True)

    card: Mapped["Card"] = relationship(back_populates="faces")
    abilities: Mapped[list["CardFaceAbility"]] = relationship(
        back_populates="face",
        cascade="all, delete-orphan",
        order_by="CardFaceAbility.ability_ix",
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "oracle_id": self.oracle_id,
            "face_ix": self.face_ix,
            "name": self.name,
            "mana_cost": self.mana_cost,
            "type_line": self.type_line,
            "oracle_text": self.oracle_text,
            "power": self.power,
            "toughness": self.toughness,
            "loyalty": self.loyalty,
            "defense": self.defense,
            "colors": self.colors,
            "color_indicator": self.color_indicator,
            "image_uris": self.image_uris,
            "artist": self.artist,
            "flavor_text": self.flavor_text,
            "cmc": self.cmc,
        }


class CardFaceAbility(Base):
    """One ability of one card face, in printed order.

    Oracle text is segmented into abilities (see `semantic.ability_split`) so
    similarity is computed over what a card *does*, rather than over one blob
    of text per face. `text_hash` is the dedup key: identical ability text
    across cards ("flying" is on ~3.2k faces) is embedded once and joined here.
    """

    __tablename__ = "card_face_abilities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["oracle_id", "face_ix"],
            ["card_faces.oracle_id", "card_faces.face_ix"],
            ondelete="CASCADE",
        ),
        Index("ix_card_face_abilities_text_hash", "text_hash"),
    )

    oracle_id: Mapped[str] = mapped_column(String, primary_key=True)
    face_ix: Mapped[int] = mapped_column(Integer, primary_key=True)
    ability_ix: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Raw ability text as printed, for display / highlighting the match.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Normalized form actually fed to the encoder.
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # True for bare keyword abilities ("Flying", "Ward {2}"). They stay indexed
    # so keyword-only creatures remain searchable, but scoring can exclude them
    # (`ignore_keywords`) and IDF de-emphasises them by default.
    # NB: `server_default="false"` as a plain string, not `text("false")` —
    # the `text` column above shadows sqlalchemy's `text()` inside this class body.
    is_keyword: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    face: Mapped["CardFace"] = relationship(back_populates="abilities")


# ---------------------------------------------------------------------------
# Tags & relationships
# ---------------------------------------------------------------------------


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tag_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tag_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tag_type: Mapped[str | None] = mapped_column(String, nullable=True)
    tag_namespace: Mapped[str | None] = mapped_column(String, nullable=True)
    tag_slug: Mapped[str | None] = mapped_column(String, nullable=True)

    card_taggings: Mapped[list["CardTagging"]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class CardTagging(Base):
    __tablename__ = "card_taggings"
    __table_args__ = (
        UniqueConstraint("card_id", "tag_id", "foreign_key", name="uq_card_taggings_card_id_tag_id_foreign_key"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.oracle_id", ondelete="CASCADE"), index=True, nullable=False)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True, nullable=False)
    foreign_key: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    tagging_type: Mapped[str | None] = mapped_column(String, nullable=True)
    weight: Mapped[str | None] = mapped_column(String, nullable=True)
    annotation: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_id: Mapped[str | None] = mapped_column(String, nullable=True)

    card: Mapped["Card"] = relationship(back_populates="taggings")
    tag: Mapped["Tag"] = relationship(back_populates="card_taggings")


class TagAncestorMap(Base):
    __tablename__ = "tag_ancestor_map"
    __table_args__ = (
        UniqueConstraint("tag_id", "ancestor_tag_id", name="uq_tag_ancestor_map_tag_id_ancestor_tag_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True, nullable=False)
    ancestor_tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True, nullable=False)


class CardRelationship(Base):
    __tablename__ = "card_relationships"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.oracle_id", ondelete="CASCADE"), index=True, nullable=False)
    foreign_key: Mapped[str | None] = mapped_column(String, nullable=True)
    classifier: Mapped[str | None] = mapped_column(String, nullable=True)
    classifier_inverse: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    relationship_type: Mapped[str | None] = mapped_column(String, nullable=True)
    weight: Mapped[str | None] = mapped_column(String, nullable=True)
    annotation: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_remote_id: Mapped[str | None] = mapped_column(String, nullable=True)
    subject_name: Mapped[str | None] = mapped_column(String, nullable=True)
    related_remote_id: Mapped[str | None] = mapped_column(String, nullable=True)
    related_name: Mapped[str | None] = mapped_column(String, nullable=True)

    card: Mapped["Card"] = relationship(back_populates="relationships")


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class SemanticModel(Base):
    __tablename__ = "semantic_models"
    __table_args__ = (
        # At most one active model at a time, enforced by the DB (not just the
        # promotion code path). Partial unique index over the single TRUE value.
        Index(
            "uq_semantic_models_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid_str)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    base_model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="uploaded", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=SEMANTIC_EMBEDDING_DIMENSION)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("semantic_datasets.id", ondelete="SET NULL"), nullable=True, index=True)
    config_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    metrics_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)
    activated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    embeddings: Mapped[list["SemanticAbilityEmbedding"]] = relationship(
        back_populates="model",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list["SemanticModelArtifact"]] = relationship(
        back_populates="model",
        cascade="all, delete-orphan",
    )
    dataset: Mapped["SemanticDataset | None"] = relationship(back_populates="models")


class SemanticDataset(Base):
    __tablename__ = "semantic_datasets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid_str)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ready", index=True)
    augmentation_mode: Mapped[str] = mapped_column(String, nullable=False, default="none")
    source_semantic_data_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    metrics_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    artifacts: Mapped[list["SemanticDatasetArtifact"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
    )
    models: Mapped[list["SemanticModel"]] = relationship(back_populates="dataset")


class SemanticModelArtifact(Base):
    __tablename__ = "semantic_model_artifacts"
    __table_args__ = (
        UniqueConstraint("model_id", "artifact_kind", name="uq_semantic_model_artifacts_model_kind"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid_str)
    model_id: Mapped[str] = mapped_column(ForeignKey("semantic_models.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    model: Mapped["SemanticModel"] = relationship(back_populates="artifacts")


class SemanticDatasetArtifact(Base):
    __tablename__ = "semantic_dataset_artifacts"
    __table_args__ = (
        UniqueConstraint("dataset_id", "artifact_kind", name="uq_semantic_dataset_artifacts_dataset_kind"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid_str)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("semantic_datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    dataset: Mapped["SemanticDataset"] = relationship(back_populates="artifacts")


class SemanticModelEmbedding(Base):
    """DEPRECATED: face-granularity embeddings, superseded by
    `SemanticAbilityEmbedding`.

    Nothing reads this table any more — it is retained so the live table is not
    dropped out from under a running deployment, and so the ORM stays an
    accurate description of the database. Migration 0007 removes it once an
    ability-based model has been promoted and verified in production.
    """

    __tablename__ = "semantic_model_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["oracle_id", "face_ix"],
            ["card_faces.oracle_id", "card_faces.face_ix"],
            ondelete="CASCADE",
        ),
    )

    model_id: Mapped[str] = mapped_column(ForeignKey("semantic_models.id", ondelete="CASCADE"), primary_key=True)
    oracle_id: Mapped[str] = mapped_column(String, primary_key=True)
    face_ix: Mapped[int] = mapped_column(Integer, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(_semantic_embedding_type(), nullable=False)


class SemanticAbilityEmbedding(Base):
    """One vector per (model, distinct ability text).

    Keyed by `text_hash` rather than by face: identical ability text is stored
    and searched once, so a kNN probe returns N *distinct* abilities instead of
    N copies of "flying" from N different cards. Faces are recovered by joining
    `card_face_abilities` on the hash.
    """

    __tablename__ = "semantic_ability_embeddings"

    model_id: Mapped[str] = mapped_column(ForeignKey("semantic_models.id", ondelete="CASCADE"), primary_key=True)
    text_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(_semantic_embedding_type(), nullable=False)

    model: Mapped["SemanticModel"] = relationship(back_populates="embeddings")


# ---------------------------------------------------------------------------
# Admin IP state
# ---------------------------------------------------------------------------

class AdminIpState(Base):
    # Tracks per-IP admin-login failures and permanent bans. Replaces an
    # earlier in-process dict so lockouts survive container restarts and
    # work across multiple workers if we ever scale out. A row exists only
    # while the IP has unresolved failure state or a standing ban; a
    # successful login deletes the row (unless banned=true).
    __tablename__ = "admin_ip_state"

    ip_address: Mapped[str] = mapped_column(String, primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    banned_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    banned_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_failure_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow_naive)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive
    )


# ---------------------------------------------------------------------------
# Semantic query log
# ---------------------------------------------------------------------------

class SemanticQueryLog(Base):
    # One row per /similar-cards request. Best-effort write — logging failures
    # do not bubble up to the response. Retention policy is operator-driven
    # (e.g. `DELETE FROM semantic_query_log WHERE created_at < now() - interval '30 days'`).
    #
    # query_mode is "text" when the caller passed `q`, or "by-face" when they
    # passed oracle_id + face_ix (find-similar-to-this-card flow).
    __tablename__ = "semantic_query_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, default=utcnow_naive, index=True)
    query_mode: Mapped[str] = mapped_column(String, nullable=False, index=True)
    client_ip: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    query_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    oracle_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    face_ix: Mapped[int | None] = mapped_column(Integer, nullable=True)
    limit_param: Mapped[int] = mapped_column(Integer, nullable=False)
    offset_param: Mapped[int] = mapped_column(Integer, nullable=False)
    filters_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
