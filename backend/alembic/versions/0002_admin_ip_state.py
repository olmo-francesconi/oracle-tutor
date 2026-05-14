"""Admin IP state.

Adds the `admin_ip_state` table for persistent per-IP admin-login throttling
and permanent IP bans. Replaces an earlier in-process dict so lockouts
survive container restarts.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_admin_ip_state"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001_initial_schema uses Base.metadata.create_all(), which blanket-
    # creates every table in the current ORM — including ones added in later
    # migrations. Skip the create when the table is already present so fresh
    # databases don't fail on re-creation.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "admin_ip_state" not in set(inspector.get_table_names()):
        op.create_table(
            "admin_ip_state",
            sa.Column("ip_address", sa.String(), primary_key=True),
            sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("banned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("banned_at", sa.DateTime(), nullable=True),
            sa.Column("banned_reason", sa.Text(), nullable=True),
            sa.Column("last_failure_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("admin_ip_state")}
    if "ix_admin_ip_state_locked_until" not in existing_indexes:
        op.create_index(
            "ix_admin_ip_state_locked_until",
            "admin_ip_state",
            ["locked_until"],
        )


def downgrade() -> None:
    op.drop_index("ix_admin_ip_state_locked_until", table_name="admin_ip_state")
    op.drop_table("admin_ip_state")
