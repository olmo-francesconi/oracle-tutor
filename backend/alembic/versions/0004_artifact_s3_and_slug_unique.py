from __future__ import annotations

import sqlalchemy as sa

from alembic import op


revision = "0004_artifact_s3_and_slug_unique"
down_revision = "0003_add_semantic_model_registry"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgresql():
        op.add_column("semantic_models", sa.Column("artifact_s3_key", sa.String(), nullable=True))
        op.alter_column("semantic_models", "artifact_bundle_bytes", existing_type=sa.LargeBinary(), nullable=True)
        op.drop_index("ix_semantic_models_slug", table_name="semantic_models")
        op.create_index("uq_semantic_models_slug", "semantic_models", ["slug"], unique=True)
    else:
        with op.batch_alter_table("semantic_models", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("artifact_s3_key", sa.String(), nullable=True))
            batch_op.alter_column("artifact_bundle_bytes", existing_type=sa.LargeBinary(), nullable=True)
            batch_op.drop_index("ix_semantic_models_slug")
            batch_op.create_index("uq_semantic_models_slug", ["slug"], unique=True)

    if _is_postgresql():
        op.execute(
            "CREATE UNIQUE INDEX uq_semantic_models_single_embedding "
            "ON semantic_models (status) WHERE status = 'embedding'"
        )
    else:
        op.execute(
            "CREATE UNIQUE INDEX uq_semantic_models_single_embedding "
            "ON semantic_models (status) WHERE status = 'embedding'"
        )


def downgrade() -> None:
    op.drop_index("uq_semantic_models_single_embedding", table_name="semantic_models")
    if _is_postgresql():
        op.drop_index("uq_semantic_models_slug", table_name="semantic_models")
        op.create_index("ix_semantic_models_slug", "semantic_models", ["slug"], unique=False)
        op.drop_column("semantic_models", "artifact_s3_key")
        op.alter_column("semantic_models", "artifact_bundle_bytes", existing_type=sa.LargeBinary(), nullable=False)
    else:
        with op.batch_alter_table("semantic_models", recreate="always") as batch_op:
            batch_op.drop_index("uq_semantic_models_slug")
            batch_op.create_index("ix_semantic_models_slug", ["slug"], unique=False)
            batch_op.drop_column("artifact_s3_key")
            batch_op.alter_column("artifact_bundle_bytes", existing_type=sa.LargeBinary(), nullable=False)
