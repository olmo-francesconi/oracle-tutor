from __future__ import annotations

import sqlalchemy as sa

from alembic import op

try:
    from sqlalchemy.dialects import postgresql
except Exception:  # pragma: no cover
    postgresql = None


revision = "0007_sem_artifacts"
down_revision = "0006_semantic_job_heartbeat"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type() -> sa.JSON:
    if _is_postgresql() and postgresql is not None:
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def upgrade() -> None:
    json_type = _json_type()
    op.create_table(
        "semantic_model_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
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
    op.create_index("ix_semantic_model_artifacts_artifact_kind", "semantic_model_artifacts", ["artifact_kind"])
    op.create_index("ix_semantic_model_artifacts_sha256", "semantic_model_artifacts", ["sha256"])
    op.create_index("ix_semantic_model_artifacts_created_at", "semantic_model_artifacts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_semantic_model_artifacts_created_at", table_name="semantic_model_artifacts")
    op.drop_index("ix_semantic_model_artifacts_sha256", table_name="semantic_model_artifacts")
    op.drop_index("ix_semantic_model_artifacts_artifact_kind", table_name="semantic_model_artifacts")
    op.drop_index("ix_semantic_model_artifacts_model_id", table_name="semantic_model_artifacts")
    op.drop_table("semantic_model_artifacts")
