from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    Vector = None


revision = "0003_sem_model_registry"
down_revision = "0002_add_telemetry_tables"
branch_labels = None
depends_on = None

SEMANTIC_EMBEDDING_DIMENSION = 384


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
    json_type = _json_type()

    op.create_table(
        "semantic_models",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("base_model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default=sa.text("384")),
        sa.Column("artifact_bundle_format", sa.String(), nullable=False, server_default=sa.text("'zip'")),
        sa.Column("artifact_bundle_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("artifact_sha256", sa.String(), nullable=False),
        sa.Column("artifact_size_bytes", sa.Integer(), nullable=False),
        sa.Column("config_json", json_type, nullable=True),
        sa.Column("metrics_json", json_type, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_semantic_models_slug", "semantic_models", ["slug"])
    op.create_index("ix_semantic_models_status", "semantic_models", ["status"])
    op.create_index("ix_semantic_models_artifact_sha256", "semantic_models", ["artifact_sha256"])
    op.create_index("ix_semantic_models_created_at", "semantic_models", ["created_at"])

    if _is_postgresql():
        op.execute(
            "CREATE UNIQUE INDEX uq_semantic_models_single_active "
            "ON semantic_models (is_active) WHERE is_active = true"
        )
    else:
        op.execute(
            "CREATE UNIQUE INDEX uq_semantic_models_single_active "
            "ON semantic_models (is_active) WHERE is_active = 1"
        )

    op.create_table(
        "semantic_model_embeddings",
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("oracle_id", sa.String(), nullable=False),
        sa.Column("face_ix", sa.Integer(), nullable=False),
        sa.Column("embedding", _embedding_type(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["semantic_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["oracle_id", "face_ix"],
            ["card_faces.oracle_id", "card_faces.face_ix"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("model_id", "oracle_id", "face_ix"),
    )
    op.create_index("ix_semantic_model_embeddings_model_id", "semantic_model_embeddings", ["model_id"])

    if _is_postgresql():
        op.execute(
            "CREATE INDEX ix_semantic_model_embeddings_embedding_hnsw "
            "ON semantic_model_embeddings USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    if _is_postgresql():
        op.drop_index("ix_semantic_model_embeddings_embedding_hnsw", table_name="semantic_model_embeddings")

    op.drop_index("ix_semantic_model_embeddings_model_id", table_name="semantic_model_embeddings")
    op.drop_table("semantic_model_embeddings")

    op.drop_index("uq_semantic_models_single_active", table_name="semantic_models")
    op.drop_index("ix_semantic_models_created_at", table_name="semantic_models")
    op.drop_index("ix_semantic_models_artifact_sha256", table_name="semantic_models")
    op.drop_index("ix_semantic_models_status", table_name="semantic_models")
    op.drop_index("ix_semantic_models_slug", table_name="semantic_models")
    op.drop_table("semantic_models")
