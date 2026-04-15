from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    Vector = None


revision = "0009_semantic_datasets_uuid"
down_revision = "0008_sem_artifacts_only"
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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in (
        "semantic_model_embeddings",
        "semantic_model_artifacts",
        "semantic_jobs",
        "semantic_models",
        "semantic_dataset_artifacts",
        "semantic_datasets",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)

    json_type = _json_type()

    op.create_table(
        "semantic_datasets",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("augmentation_mode", sa.String(), nullable=False),
        sa.Column("source_semantic_data_version", sa.Integer(), nullable=True),
        sa.Column("config_json", json_type, nullable=True),
        sa.Column("metrics_json", json_type, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_semantic_datasets_slug"),
    )
    op.create_index("ix_semantic_datasets_status", "semantic_datasets", ["status"])
    op.create_index("ix_semantic_datasets_created_at", "semantic_datasets", ["created_at"])

    op.create_table(
        "semantic_models",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("base_model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default=sa.text("384")),
        sa.Column("dataset_id", sa.String(), nullable=True),
        sa.Column("config_json", json_type, nullable=True),
        sa.Column("metrics_json", json_type, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["semantic_datasets.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("slug", name="uq_semantic_models_slug"),
    )
    op.create_index("ix_semantic_models_status", "semantic_models", ["status"])
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
        "semantic_dataset_artifacts",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("dataset_id", sa.String(), nullable=False),
        sa.Column("artifact_kind", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("metadata_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["dataset_id"], ["semantic_datasets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("dataset_id", "artifact_kind", name="uq_semantic_dataset_artifacts_dataset_kind"),
    )
    op.create_index("ix_semantic_dataset_artifacts_dataset_id", "semantic_dataset_artifacts", ["dataset_id"])

    op.create_table(
        "semantic_model_artifacts",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("artifact_kind", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("metadata_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["model_id"], ["semantic_models.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("model_id", "artifact_kind", name="uq_semantic_model_artifacts_model_kind"),
    )
    op.create_index("ix_semantic_model_artifacts_model_id", "semantic_model_artifacts", ["model_id"])

    op.create_table(
        "semantic_model_embeddings",
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("oracle_id", sa.String(), nullable=False),
        sa.Column("face_ix", sa.Integer(), nullable=False),
        sa.Column("embedding", _embedding_type(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["semantic_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["oracle_id", "face_ix"], ["card_faces.oracle_id", "card_faces.face_ix"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("model_id", "oracle_id", "face_ix"),
    )
    op.create_index("ix_semantic_model_embeddings_model_id", "semantic_model_embeddings", ["model_id"])
    if _is_postgresql():
        op.execute(
            "CREATE INDEX ix_semantic_model_embeddings_embedding_hnsw "
            "ON semantic_model_embeddings USING hnsw (embedding vector_cosine_ops)"
        )

    op.create_table(
        "semantic_jobs",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("dataset_id", sa.String(), nullable=True),
        sa.Column("payload_json", json_type, nullable=False),
        sa.Column("result_json", json_type, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["semantic_models.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dataset_id"], ["semantic_datasets.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_semantic_jobs_job_type", "semantic_jobs", ["job_type"])
    op.create_index("ix_semantic_jobs_status", "semantic_jobs", ["status"])
    op.create_index("ix_semantic_jobs_model_id", "semantic_jobs", ["model_id"])
    op.create_index("ix_semantic_jobs_dataset_id", "semantic_jobs", ["dataset_id"])
    op.create_index("ix_semantic_jobs_created_at", "semantic_jobs", ["created_at"])


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for the semantic UUID/dataset split migration.")
