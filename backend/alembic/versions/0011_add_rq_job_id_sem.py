from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_add_rq_job_id_sem"
down_revision = "0010_drop_face_sem_embeds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("semantic_jobs", sa.Column("rq_job_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("semantic_jobs", "rq_job_id")
