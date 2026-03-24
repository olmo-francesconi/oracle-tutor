from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    Vector = None


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

SEMANTIC_EMBEDDING_DIMENSION = 384
TABLES_TO_DROP = [
    "card_face_semantic_embeddings",
    "card_faces",
    "card_taggings",
    "tag_ancestor_map",
    "card_relationships",
    "cards",
    "cards_raw",
    "tags",
    "ingestion_logs",
    "system_metadata",
]


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type() -> sa.JSON:
    if _is_postgresql():
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _embedding_type() -> sa.TypeEngine[object]:
    if _is_postgresql() and Vector is not None:
        return Vector(SEMANTIC_EMBEDDING_DIMENSION)
    return sa.JSON()


def upgrade() -> None:
    for table_name in TABLES_TO_DROP:
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{table_name}"'))

    if _is_postgresql():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    json_type = _json_type()

    op.create_table(
        "system_metadata",
        sa.Column("key", sa.String(), primary_key=True, nullable=False),
        sa.Column("data_updated_at", sa.String(), nullable=False),
        sa.Column("last_ingestion", sa.DateTime(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=True),
    )

    op.create_table(
        "ingestion_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("records_processed", sa.Integer(), nullable=False),
        sa.Column("records_skipped", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("trigger_type", sa.String(), nullable=True),
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("tag_name", sa.String(), nullable=False),
        sa.Column("tag_description", sa.Text(), nullable=True),
        sa.Column("tag_type", sa.String(), nullable=True),
        sa.Column("tag_namespace", sa.String(), nullable=True),
        sa.Column("tag_slug", sa.String(), nullable=True),
    )
    op.create_index("ix_tags_tag_name", "tags", ["tag_name"])

    op.create_table(
        "cards_raw",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("oracle_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("lang", sa.String(), nullable=False),
        sa.Column("layout", sa.String(), nullable=False),
        sa.Column("cmc", sa.Float(), nullable=True),
        sa.Column("mana_cost", sa.String(), nullable=True),
        sa.Column("type_line", sa.String(), nullable=True),
        sa.Column("oracle_text", sa.Text(), nullable=True),
        sa.Column("colors", json_type, nullable=True),
        sa.Column("color_identity", json_type, nullable=False),
        sa.Column("color_indicator", json_type, nullable=True),
        sa.Column("keywords", json_type, nullable=False),
        sa.Column("legalities", json_type, nullable=False),
        sa.Column("power", sa.String(), nullable=True),
        sa.Column("toughness", sa.String(), nullable=True),
        sa.Column("loyalty", sa.String(), nullable=True),
        sa.Column("defense", sa.String(), nullable=True),
        sa.Column("rarity", sa.String(), nullable=False),
        sa.Column("set_code", sa.String(), nullable=False),
        sa.Column("set_id", sa.String(), nullable=False),
        sa.Column("set_name", sa.String(), nullable=False),
        sa.Column("set_type", sa.String(), nullable=False),
        sa.Column("collector_number", sa.String(), nullable=False),
        sa.Column("released_at", sa.Date(), nullable=True),
        sa.Column("artist", sa.String(), nullable=True),
        sa.Column("illustration_id", sa.String(), nullable=True),
        sa.Column("image_status", sa.String(), nullable=True),
        sa.Column("image_uris", json_type, nullable=True),
        sa.Column("card_faces_json", json_type, nullable=True),
        sa.Column("all_parts", json_type, nullable=True),
        sa.Column("games", json_type, nullable=False),
        sa.Column("finishes", json_type, nullable=False),
        sa.Column("digital", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("booster", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("promo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("promo_types", json_type, nullable=True),
        sa.Column("reprint", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("variation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("variation_of", sa.String(), nullable=True),
        sa.Column("full_art", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("textless", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("story_spotlight", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("border_color", sa.String(), nullable=True),
        sa.Column("frame", sa.String(), nullable=True),
        sa.Column("frame_effects", json_type, nullable=True),
        sa.Column("watermark", sa.String(), nullable=True),
        sa.Column("edhrec_rank", sa.Integer(), nullable=True),
        sa.Column("prices", json_type, nullable=True),
        sa.Column("arena_id", sa.Integer(), nullable=True),
        sa.Column("mtgo_id", sa.Integer(), nullable=True),
        sa.Column("tcgplayer_id", sa.Integer(), nullable=True),
        sa.Column("cardmarket_id", sa.Integer(), nullable=True),
        sa.Column("multiverse_ids", json_type, nullable=True),
        sa.Column("flavor_text", sa.Text(), nullable=True),
        sa.Column("flavor_name", sa.String(), nullable=True),
        sa.Column("content_warning", sa.Boolean(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_cards_raw_oracle_id", "cards_raw", ["oracle_id"])
    op.create_index("ix_cards_raw_set_code", "cards_raw", ["set_code"])
    op.create_index("ix_cards_raw_edhrec_rank", "cards_raw", ["edhrec_rank"])

    op.create_table(
        "cards",
        sa.Column("oracle_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("scryfall_id", sa.String(), sa.ForeignKey("cards_raw.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("layout", sa.String(), nullable=True),
        sa.Column("cmc", sa.Float(), nullable=True),
        sa.Column("color_identity", json_type, nullable=True),
        sa.Column("legalities", json_type, nullable=True),
        sa.Column("edhrec_rank", sa.Integer(), nullable=True),
        sa.Column("rarity", sa.String(), nullable=True),
        sa.Column("uniqueness", sa.Float(), nullable=True),
    )
    op.create_index("ix_cards_name", "cards", ["name"])
    op.create_index("ix_cards_edhrec_rank", "cards", ["edhrec_rank"])

    op.create_table(
        "card_faces",
        sa.Column("oracle_id", sa.String(), nullable=False),
        sa.Column("face_ix", sa.Integer(), nullable=False),
        sa.Column("scryfall_face_oracle_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("mana_cost", sa.String(), nullable=True),
        sa.Column("type_line", sa.String(), nullable=True),
        sa.Column("oracle_text", sa.Text(), nullable=True),
        sa.Column("power", sa.String(), nullable=True),
        sa.Column("toughness", sa.String(), nullable=True),
        sa.Column("loyalty", sa.String(), nullable=True),
        sa.Column("defense", sa.String(), nullable=True),
        sa.Column("colors", json_type, nullable=True),
        sa.Column("color_indicator", json_type, nullable=True),
        sa.Column("image_uris", json_type, nullable=True),
        sa.Column("artist", sa.String(), nullable=True),
        sa.Column("flavor_text", sa.Text(), nullable=True),
        sa.Column("cmc", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["oracle_id"], ["cards.oracle_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("oracle_id", "face_ix"),
    )
    op.create_index("ix_card_faces_scryfall_face_oracle_id", "card_faces", ["scryfall_face_oracle_id"])
    op.create_index("ix_card_faces_name", "card_faces", ["name"])

    op.create_table(
        "card_face_semantic_embeddings",
        sa.Column("oracle_id", sa.String(), nullable=False),
        sa.Column("face_ix", sa.Integer(), nullable=False),
        sa.Column("embedding", _embedding_type(), nullable=False),
        sa.ForeignKeyConstraint(
            ["oracle_id", "face_ix"],
            ["card_faces.oracle_id", "card_faces.face_ix"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("oracle_id", "face_ix"),
    )

    op.create_table(
        "card_taggings",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("card_id", sa.String(), sa.ForeignKey("cards.oracle_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", sa.String(), sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("foreign_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("tagging_type", sa.String(), nullable=True),
        sa.Column("weight", sa.String(), nullable=True),
        sa.Column("annotation", sa.Text(), nullable=True),
        sa.Column("related_id", sa.String(), nullable=True),
        sa.UniqueConstraint("card_id", "tag_id", "foreign_key", name="uq_card_taggings_card_id_tag_id_foreign_key"),
    )
    op.create_index("ix_card_taggings_card_id", "card_taggings", ["card_id"])
    op.create_index("ix_card_taggings_tag_id", "card_taggings", ["tag_id"])

    op.create_table(
        "tag_ancestor_map",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("tag_id", sa.String(), sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ancestor_tag_id", sa.String(), sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("tag_id", "ancestor_tag_id", name="uq_tag_ancestor_map_tag_id_ancestor_tag_id"),
    )
    op.create_index("ix_tag_ancestor_map_tag_id", "tag_ancestor_map", ["tag_id"])
    op.create_index("ix_tag_ancestor_map_ancestor_tag_id", "tag_ancestor_map", ["ancestor_tag_id"])

    op.create_table(
        "card_relationships",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("card_id", sa.String(), sa.ForeignKey("cards.oracle_id", ondelete="CASCADE"), nullable=False),
        sa.Column("foreign_key", sa.String(), nullable=True),
        sa.Column("classifier", sa.String(), nullable=True),
        sa.Column("classifier_inverse", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("relationship_type", sa.String(), nullable=True),
        sa.Column("weight", sa.String(), nullable=True),
        sa.Column("annotation", sa.Text(), nullable=True),
        sa.Column("subject_remote_id", sa.String(), nullable=True),
        sa.Column("subject_name", sa.String(), nullable=True),
        sa.Column("related_remote_id", sa.String(), nullable=True),
        sa.Column("related_name", sa.String(), nullable=True),
    )
    op.create_index("ix_card_relationships_card_id", "card_relationships", ["card_id"])

    if _is_postgresql():
        op.execute("CREATE INDEX ix_cards_name_trgm ON cards USING gin (name gin_trgm_ops)")
        op.execute("CREATE INDEX ix_card_faces_name_trgm ON card_faces USING gin (name gin_trgm_ops)")
        op.execute("CREATE INDEX ix_card_faces_oracle_text_trgm ON card_faces USING gin (oracle_text gin_trgm_ops)")
        op.execute(
            "CREATE INDEX ix_card_face_semantic_embeddings_embedding_hnsw "
            "ON card_face_semantic_embeddings USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    for table_name in TABLES_TO_DROP:
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{table_name}"'))
