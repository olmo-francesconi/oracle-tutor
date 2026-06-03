"""Enforce a single active semantic model at the DB level.

Adds a partial unique index over `semantic_models.is_active` (TRUE only), so
at most one model can be active regardless of application-level races in the
promotion path. Before creating the index we defensively collapse any
pre-existing multi-active state (keeping the most recently activated/created).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_active_model_unique"
down_revision = "0003_semantic_query_log"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_semantic_models_single_active"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "semantic_models" not in set(inspector.get_table_names()):
        return

    # Collapse any accidental multi-active state so the unique index can build.
    # Keep the most recently activated (falling back to created) row active.
    bind.execute(
        sa.text(
            """
            UPDATE semantic_models
               SET is_active = FALSE,
                   status = CASE WHEN status = 'active' THEN 'ready' ELSE status END
             WHERE is_active = TRUE
               AND id <> (
                   SELECT id FROM semantic_models
                    WHERE is_active = TRUE
                    ORDER BY activated_at DESC NULLS LAST, created_at DESC
                    LIMIT 1
               )
            """
        )
    )

    existing = {idx["name"] for idx in inspector.get_indexes("semantic_models")}
    if _INDEX_NAME not in existing:
        op.create_index(
            _INDEX_NAME,
            "semantic_models",
            ["is_active"],
            unique=True,
            postgresql_where=sa.text("is_active"),
        )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="semantic_models")
