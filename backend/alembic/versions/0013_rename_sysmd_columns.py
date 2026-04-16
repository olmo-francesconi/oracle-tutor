from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013_rename_sysmd_columns"
down_revision = "0012_drop_rq_job_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("ALTER TABLE system_metadata RENAME COLUMN schema_version TO version")
        op.execute("ALTER TABLE system_metadata RENAME COLUMN data_updated_at TO updated_at")
    else:
        with op.batch_alter_table("system_metadata") as batch_op:
            batch_op.alter_column("schema_version", new_column_name="version", existing_type=sa.String())
            batch_op.alter_column("data_updated_at", new_column_name="updated_at", existing_type=sa.String())


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("ALTER TABLE system_metadata RENAME COLUMN version TO schema_version")
        op.execute("ALTER TABLE system_metadata RENAME COLUMN updated_at TO data_updated_at")
    else:
        with op.batch_alter_table("system_metadata") as batch_op:
            batch_op.alter_column("version", new_column_name="schema_version", existing_type=sa.String())
            batch_op.alter_column("updated_at", new_column_name="data_updated_at", existing_type=sa.String())
