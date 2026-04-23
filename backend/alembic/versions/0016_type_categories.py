from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016_type_categories"
down_revision = "0015_drop_telemetry"
branch_labels = None
depends_on = None


_KNOWN_TYPES = ("creature", "instant", "sorcery", "enchantment", "artifact", "planeswalker", "land")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        op.add_column(
            "card_faces",
            sa.Column("type_categories", postgresql.ARRAY(sa.Text()), nullable=True),
        )

        # Backfill: parse the existing `type_line` left of the em dash. Runs
        # once at migration time — the ~60k faces × 7 ILIKE terms is well under
        # a second on a warm cache.
        case_parts = ", ".join(
            f"CASE WHEN type_line ILIKE '%{t}%' THEN '{t}' END" for t in _KNOWN_TYPES
        )
        op.execute(
            f"""
            UPDATE card_faces
            SET type_categories = array_remove(ARRAY[{case_parts}]::text[], NULL)
            WHERE type_line IS NOT NULL
            """
        )

        op.create_index(
            "ix_card_faces_type_categories",
            "card_faces",
            ["type_categories"],
            postgresql_using="gin",
        )
    else:
        # SQLite: no array type / no GIN. JSON-backed column is enough for the
        # ORM round-trip; tests continue to fall through the ilike path.
        op.add_column("card_faces", sa.Column("type_categories", sa.JSON(), nullable=True))


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.drop_index("ix_card_faces_type_categories", table_name="card_faces")
    op.drop_column("card_faces", "type_categories")
