"""Drop semantic_jobs table — no longer needed after job orchestration redesign."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text

revision = "0002_drop_semantic_jobs"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: 0001 builds the schema from current ORM models via
    # Base.metadata.create_all, so on a fresh DB the table never existed.
    op.execute("DROP TABLE IF EXISTS semantic_jobs CASCADE")


def downgrade() -> None:
    op.create_table(
        "semantic_jobs",
        Column("id", String, primary_key=True),
        Column("job_type", String, nullable=False, index=True),
        Column("status", String, nullable=False, index=True),
        Column("requested_by", String, nullable=False),
        Column("model_id", String, ForeignKey("semantic_models.id", ondelete="SET NULL"), nullable=True, index=True),
        Column("dataset_id", String, ForeignKey("semantic_datasets.id", ondelete="SET NULL"), nullable=True, index=True),
        Column("payload_json", JSON, nullable=False),
        Column("result_json", JSON, nullable=True),
        Column("error_message", Text, nullable=True),
        Column("created_at", DateTime, nullable=False),
        Column("started_at", DateTime, nullable=True),
        Column("heartbeat_at", DateTime, nullable=True),
        Column("finished_at", DateTime, nullable=True),
    )
