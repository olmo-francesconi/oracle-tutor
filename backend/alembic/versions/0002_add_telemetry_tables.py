from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "0002_add_telemetry_tables"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type() -> sa.JSON:
    if _is_postgresql():
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def upgrade() -> None:
    json_type = _json_type()

    op.create_table(
        "client_error_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("error_name", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("context", json_type, nullable=True),
    )
    op.create_index("ix_client_error_events_occurred_at", "client_error_events", ["occurred_at"])
    op.create_index("ix_client_error_events_source", "client_error_events", ["source"])

    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("event_name", sa.String(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("props", json_type, nullable=True),
    )
    op.create_index("ix_analytics_events_occurred_at", "analytics_events", ["occurred_at"])
    op.create_index("ix_analytics_events_event_name", "analytics_events", ["event_name"])


def downgrade() -> None:
    op.drop_index("ix_analytics_events_event_name", table_name="analytics_events")
    op.drop_index("ix_analytics_events_occurred_at", table_name="analytics_events")
    op.drop_table("analytics_events")

    op.drop_index("ix_client_error_events_source", table_name="client_error_events")
    op.drop_index("ix_client_error_events_occurred_at", table_name="client_error_events")
    op.drop_table("client_error_events")
