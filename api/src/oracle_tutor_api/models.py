from sqlalchemy import String, Integer, Float, Text, JSON, ARRAY, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from .database import Base
import datetime

class SystemMetadata(Base):
    __tablename__ = "system_metadata"
    
    # Singleton key, usually just "scryfall_data"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    
    # When the data was updated on Scryfall side
    data_updated_at: Mapped[str] = mapped_column(String) 
    
    # When we performed the ingestion
    last_ingestion: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

class Card(Base):
    __tablename__ = "cards"

    # Scryfall ID is a UUID, but we'll store as string
    id: Mapped[str] = mapped_column(String, primary_key=True)
    
    # Basic Card Data (Shared)
    name: Mapped[str] = mapped_column(String, index=True)
    
    # Some stats are per-card (like rank, rarity, legality)
    edhrec_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rarity: Mapped[str | None] = mapped_column(String, nullable=True)
    legalities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    # Relationships
    faces: Mapped[list["CardFace"]] = relationship(back_populates="card", cascade="all, delete-orphan")

    def to_dict(self):
        """Helper to convert model to dictionary for API responses"""
        return {
            "id": self.id,
            "name": self.name,
            "edhrec_rank": self.edhrec_rank,
            "rarity": self.rarity,
            "legalities": self.legalities,
            "faces": [face.to_dict() for face in self.faces]
        }

class CardFace(Base):
    __tablename__ = "card_faces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    
    name: Mapped[str] = mapped_column(String, index=True)
    mana_cost: Mapped[str | None] = mapped_column(String, nullable=True)
    type_line: Mapped[str | None] = mapped_column(String, nullable=True)
    oracle_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Stats
    power: Mapped[str | None] = mapped_column(String, nullable=True)
    toughness: Mapped[str | None] = mapped_column(String, nullable=True)
    colors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    
    # The Embedding Vector for Semantic Search
    # 384 dimensions corresponds to 'all-MiniLM-L6-v2' model
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))

    # Relationship
    card: Mapped["Card"] = relationship(back_populates="faces")

    def to_dict(self):
        return {
            "name": self.name,
            "mana_cost": self.mana_cost,
            "type_line": self.type_line,
            "oracle_text": self.oracle_text,
            "power": self.power,
            "toughness": self.toughness,
            "colors": self.colors
        }
