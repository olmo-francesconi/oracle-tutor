from __future__ import annotations

import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

try:
    from pgvector.sqlalchemy import Vector as PgVector
except Exception:  # pragma: no cover - optional dependency for sqlite tests
    PgVector = None


SEMANTIC_EMBEDDING_DIMENSION = 384


def _semantic_embedding_type():
    if PgVector is None:
        return JSON
    return PgVector(SEMANTIC_EMBEDDING_DIMENSION)


def _utcnow_naive() -> datetime.datetime:
    """Return naive UTC datetime without deprecated utcnow()."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class SystemMetadata(Base):
    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    data_updated_at: Mapped[str] = mapped_column(String)
    last_ingestion: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow_naive)
    schema_version: Mapped[str | None] = mapped_column(String, default="0.0")


class IngestionLog(Base):
    __tablename__ = "ingestion_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_utcnow_naive)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String)  # started/success/failed
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[str] = mapped_column(String)
    trigger_type: Mapped[str | None] = mapped_column(String, nullable=True)


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    scryfall_set: Mapped[str | None] = mapped_column(String, nullable=True)
    collector_number: Mapped[str | None] = mapped_column(String, nullable=True)
    layout: Mapped[str | None] = mapped_column(String, nullable=True)
    cmc: Mapped[float | None] = mapped_column(Float, nullable=True)
    edhrec_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rarity: Mapped[str | None] = mapped_column(String, nullable=True)
    color_identity: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    legalities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    uniqueness: Mapped[float | None] = mapped_column(Float, nullable=True)

    faces: Mapped[list["CardFace"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    taggings: Mapped[List["CardTagging"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    relationships: Mapped[List["CardRelationship"]] = relationship(back_populates="card", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "layout": self.layout,
            "cmc": self.cmc,
            "edhrec_rank": self.edhrec_rank,
            "rarity": self.rarity,
            "legalities": self.legalities,
            "uniqueness": self.uniqueness,
            "faces": [f.to_dict() for f in self.faces],
        }


class CardFace(Base):
    __tablename__ = "card_faces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String, index=True)
    mana_cost: Mapped[str | None] = mapped_column(String, nullable=True)
    type_line: Mapped[str | None] = mapped_column(String, nullable=True)
    oracle_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    power: Mapped[str | None] = mapped_column(String, nullable=True)
    toughness: Mapped[str | None] = mapped_column(String, nullable=True)
    colors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    card: Mapped["Card"] = relationship(back_populates="faces")
    semantic_embedding: Mapped[Optional["CardFaceSemanticEmbedding"]] = relationship(
        back_populates="face",
        uselist=False,
        cascade="all, delete-orphan",
        single_parent=True,
    )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "mana_cost": self.mana_cost,
            "type_line": self.type_line,
            "oracle_text": self.oracle_text,
            "power": self.power,
            "toughness": self.toughness,
            "colors": self.colors,
        }


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tag_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tag_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tag_type: Mapped[str | None] = mapped_column(String, nullable=True)
    tag_namespace: Mapped[str | None] = mapped_column(String, nullable=True)
    tag_slug: Mapped[str | None] = mapped_column(String, nullable=True)

    card_taggings: Mapped[List["CardTagging"]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class CardTagging(Base):
    __tablename__ = "card_taggings"
    __table_args__ = (
        UniqueConstraint("card_id", "tag_id", "foreign_key", name="uq_card_taggings_card_id_tag_id_foreign_key"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True, nullable=False)
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
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True, nullable=False)
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


class CardFaceSemanticEmbedding(Base):
    __tablename__ = "card_face_semantic_embeddings"

    face_id: Mapped[int] = mapped_column(ForeignKey("card_faces.id", ondelete="CASCADE"), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(_semantic_embedding_type(), nullable=False)

    face: Mapped["CardFace"] = relationship(back_populates="semantic_embedding")
