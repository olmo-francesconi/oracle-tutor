from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012_drop_rq_job_id"
down_revision = "0011_add_rq_job_id_to_semantic_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("semantic_jobs", "rq_job_id")


def downgrade() -> None:
    op.add_column("semantic_jobs", sa.Column("rq_job_id", sa.String(), nullable=True))
