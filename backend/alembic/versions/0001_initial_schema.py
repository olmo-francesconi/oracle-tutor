"""Initial schema squashed from the 16 migrations that predate v2.0.0.

The schema is the single source of truth defined by the ORM models in
`ot_backend.core.models`. This migration creates every table via
`Base.metadata.create_all`, then layers on the pgvector HNSW index on
`semantic_model_embeddings.embedding` and the GIN index on
`card_faces.type_categories` — neither is expressible as a declarative model
attribute.
"""

from __future__ import annotations

from alembic import op
from ot_backend.core import models  # noqa: F401 — registers tables on Base.metadata
from ot_backend.core.database import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    Base.metadata.create_all(bind=bind)

    op.create_index(
        "ix_card_faces_type_categories",
        "card_faces",
        ["type_categories"],
        postgresql_using="gin",
    )

    op.execute(
        "CREATE INDEX ix_semantic_model_embeddings_embedding_hnsw "
        "ON semantic_model_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP INDEX IF EXISTS ix_semantic_model_embeddings_embedding_hnsw")
    op.drop_index("ix_card_faces_type_categories", table_name="card_faces")
    Base.metadata.drop_all(bind=bind)
    op.execute("DROP EXTENSION IF EXISTS vector")
