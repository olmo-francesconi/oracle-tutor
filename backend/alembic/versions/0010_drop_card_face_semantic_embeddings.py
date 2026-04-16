from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_drop_card_face_semantic_embeddings"
down_revision = "0009_semantic_datasets_uuid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("card_face_semantic_embeddings"):
        op.drop_table("card_face_semantic_embeddings")


def downgrade() -> None:
    op.create_table(
        "card_face_semantic_embeddings",
        sa.Column("oracle_id", sa.String(), nullable=False),
        sa.Column("face_ix", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["oracle_id", "face_ix"],
            ["card_faces.oracle_id", "card_faces.face_ix"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("oracle_id", "face_ix"),
    )
