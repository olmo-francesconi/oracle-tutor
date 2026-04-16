from __future__ import annotations

import sqlalchemy as sa

from alembic import op


revision = "0006_semantic_job_heartbeat"
down_revision = "0005_add_semantic_jobs"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column("semantic_jobs", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
    op.execute(
        "CREATE UNIQUE INDEX uq_semantic_jobs_single_active_promote "
        "ON semantic_jobs (job_type) "
        "WHERE job_type = 'promote' AND status IN ('pending', 'running')"
    )


def downgrade() -> None:
    op.drop_index("uq_semantic_jobs_single_active_promote", table_name="semantic_jobs")
    if _is_postgresql():
        op.drop_column("semantic_jobs", "heartbeat_at")
    else:
        with op.batch_alter_table("semantic_jobs", recreate="always") as batch_op:
            batch_op.drop_column("heartbeat_at")
