from __future__ import annotations

import sqlalchemy as sa

from alembic import op

try:
    from sqlalchemy.dialects import postgresql
except Exception:  # pragma: no cover
    postgresql = None


revision = "0005_add_semantic_jobs"
down_revision = "0004_artf_s3_slug_uniq"
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
        "semantic_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("payload_json", json_type, nullable=False),
        sa.Column("result_json", json_type, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["semantic_models.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_semantic_jobs_created_at", "semantic_jobs", ["created_at"])
    op.create_index("ix_semantic_jobs_status", "semantic_jobs", ["status"])
    op.create_index("ix_semantic_jobs_job_type", "semantic_jobs", ["job_type"])
    op.create_index("ix_semantic_jobs_model_id", "semantic_jobs", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_semantic_jobs_model_id", table_name="semantic_jobs")
    op.drop_index("ix_semantic_jobs_job_type", table_name="semantic_jobs")
    op.drop_index("ix_semantic_jobs_status", table_name="semantic_jobs")
    op.drop_index("ix_semantic_jobs_created_at", table_name="semantic_jobs")
    op.drop_table("semantic_jobs")
