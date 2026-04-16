from __future__ import annotations

import sqlalchemy as sa

from alembic import op


revision = "0008_sem_artifacts_only"
down_revision = "0007_sem_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_semantic_models_artifact_sha256", table_name="semantic_models")
    op.drop_column("semantic_models", "artifact_bundle_format")
    op.drop_column("semantic_models", "artifact_bundle_bytes")
    op.drop_column("semantic_models", "artifact_s3_key")
    op.drop_column("semantic_models", "artifact_sha256")
    op.drop_column("semantic_models", "artifact_size_bytes")


def downgrade() -> None:
    op.add_column("semantic_models", sa.Column("artifact_size_bytes", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("semantic_models", sa.Column("artifact_sha256", sa.String(), nullable=False, server_default=""))
    op.add_column("semantic_models", sa.Column("artifact_s3_key", sa.String(), nullable=True))
    op.add_column("semantic_models", sa.Column("artifact_bundle_bytes", sa.LargeBinary(), nullable=True))
    op.add_column(
        "semantic_models",
        sa.Column("artifact_bundle_format", sa.String(), nullable=False, server_default="zip"),
    )
    op.create_index("ix_semantic_models_artifact_sha256", "semantic_models", ["artifact_sha256"])
