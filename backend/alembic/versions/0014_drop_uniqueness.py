from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014_drop_uniqueness"
down_revision = "0013_rename_sysmd_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cards") as batch_op:
        batch_op.drop_column("uniqueness")


def downgrade() -> None:
    with op.batch_alter_table("cards") as batch_op:
        batch_op.add_column(sa.Column("uniqueness", sa.Float(), nullable=True))
