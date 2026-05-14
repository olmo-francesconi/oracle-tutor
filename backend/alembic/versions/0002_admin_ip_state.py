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
    op.create_index(
        "ix_admin_ip_state_locked_until",
        "admin_ip_state",
        ["locked_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_ip_state_locked_until", table_name="admin_ip_state")
    op.drop_table("admin_ip_state")
