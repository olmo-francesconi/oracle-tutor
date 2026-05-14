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
    # 0001_initial_schema uses Base.metadata.create_all(), which blanket-
    # creates every table in the current ORM — including ones added in later
    # migrations. Skip the create when the table is already present.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "semantic_query_log" not in set(inspector.get_table_names()):
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
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("semantic_query_log")}
    for index_name, columns in (
        ("ix_semantic_query_log_created_at", ["created_at"]),
        ("ix_semantic_query_log_query_mode", ["query_mode"]),
        ("ix_semantic_query_log_client_ip", ["client_ip"]),
        ("ix_semantic_query_log_oracle_id", ["oracle_id"]),
        ("ix_semantic_query_log_model_id", ["model_id"]),
    ):
        if index_name not in existing_indexes:
            op.create_index(index_name, "semantic_query_log", columns)


def downgrade() -> None:
    op.drop_index("ix_semantic_query_log_model_id", table_name="semantic_query_log")
    op.drop_index("ix_semantic_query_log_oracle_id", table_name="semantic_query_log")
    op.drop_index("ix_semantic_query_log_client_ip", table_name="semantic_query_log")
    op.drop_index("ix_semantic_query_log_query_mode", table_name="semantic_query_log")
    op.drop_index("ix_semantic_query_log_created_at", table_name="semantic_query_log")
    op.drop_table("semantic_query_log")
