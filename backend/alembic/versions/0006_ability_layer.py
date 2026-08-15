"""Ability layer: per-ability segmentation and embeddings.

Adds the [card] -> [card_face] -> [ability] level:

* `card_face_abilities` — one row per ability of a face, in printed order.
* `semantic_ability_embeddings` — one vector per (model, distinct ability
  text). Keyed by `text_hash` rather than by face so identical ability text
  is embedded and searched once.

Deliberately ADDITIVE. `semantic_model_embeddings` (face granularity) is left
in place so a running deployment keeps serving while an ability-based model is
promoted and verified. A later migration drops it.

Like the face table before it, there is no HNSW index on the embedding column:
retrieval applies SQL filters alongside the distance ordering, and pgvector's
HNSW post-filters, which would silently cost recall on filtered searches. Exact
cosine over ~37k distinct abilities is fast enough.

Columns are spelled out rather than built from `Base.metadata`: a migration is
a snapshot of the schema at this revision, and generating it from the live ORM
means the migration silently changes whenever a model gains a column. (That
exact drift broke this pair once — 0007's `is_keyword` was already being
created here, so `ADD COLUMN` failed on a fresh database.)
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "0006_ability_layer"
down_revision = "0005_card_jsonb_and_fk"
branch_labels = None
depends_on = None

_EMBEDDING_DIM = 384


def upgrade() -> None:
    # 0001_initial_schema uses Base.metadata.create_all(), which blanket-creates
    # every table in the current ORM — including ones added in later migrations.
    # Same guard as 0002/0003 so fresh databases don't fail on re-creation.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "card_face_abilities" not in existing_tables:
        _create_card_face_abilities()
    if "ix_card_face_abilities_text_hash" not in {
        idx["name"] for idx in inspector.get_indexes("card_face_abilities")
    }:
        op.create_index("ix_card_face_abilities_text_hash", "card_face_abilities", ["text_hash"])

    if "semantic_ability_embeddings" not in existing_tables:
        _create_semantic_ability_embeddings()


def _create_card_face_abilities() -> None:
    op.create_table(
        "card_face_abilities",
        sa.Column("oracle_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("face_ix", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("ability_ix", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["oracle_id", "face_ix"],
            ["card_faces.oracle_id", "card_faces.face_ix"],
            ondelete="CASCADE",
        ),
    )


def _create_semantic_ability_embeddings() -> None:
    op.create_table(
        "semantic_ability_embeddings",
        sa.Column("model_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("text_hash", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["semantic_models.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("semantic_ability_embeddings")
    op.drop_index("ix_card_face_abilities_text_hash", table_name="card_face_abilities")
    op.drop_table("card_face_abilities")
