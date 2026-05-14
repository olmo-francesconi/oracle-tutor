"""Semantic query log.

Adds the `semantic_query_log` table. One row per /similar-cards request,
written best-effort. The `query_mode` column distinguishes "text"
(free-text query via `q`) from "by-face" (oracle_id + face_ix lookup).
Retention policy is operator-driven (no automatic purge).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_semantic_query_log"
down_revision = "0002_admin_ip_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_query_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("query_mode", sa.String(), nullable=False),
        sa.Column("client_ip", sa.String(), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column("oracle_id", sa.String(), nullable=True),
        sa.Column("face_ix", sa.Integer(), nullable=True),
        sa.Column("limit_param", sa.Integer(), nullable=False),
        sa.Column("offset_param", sa.Integer(), nullable=False),
        sa.Column("filters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_semantic_query_log_created_at", "semantic_query_log", ["created_at"])
    op.create_index("ix_semantic_query_log_query_mode", "semantic_query_log", ["query_mode"])
    op.create_index("ix_semantic_query_log_client_ip", "semantic_query_log", ["client_ip"])
    op.create_index("ix_semantic_query_log_oracle_id", "semantic_query_log", ["oracle_id"])
    op.create_index("ix_semantic_query_log_model_id", "semantic_query_log", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_semantic_query_log_model_id", table_name="semantic_query_log")
    op.drop_index("ix_semantic_query_log_oracle_id", table_name="semantic_query_log")
    op.drop_index("ix_semantic_query_log_client_ip", table_name="semantic_query_log")
    op.drop_index("ix_semantic_query_log_query_mode", table_name="semantic_query_log")
    op.drop_index("ix_semantic_query_log_created_at", table_name="semantic_query_log")
    op.drop_table("semantic_query_log")
