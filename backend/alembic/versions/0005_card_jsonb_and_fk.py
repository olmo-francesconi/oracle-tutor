"""Unify the card hierarchy on JSONB and make the cards->cards_raw FK explicit.

- Converts the remaining `JSON` columns on `cards_raw` / `card_faces` to
  `JSONB`, matching `cards`/`card_faces` filter columns that were already JSONB.
- Replaces the implicit NO ACTION on `cards.scryfall_id` with an explicit
  `ON DELETE RESTRICT`, codifying the invariant the ingest delete-phase already
  upholds (a cards row's best-printing pointer always references a kept raw row).

These ALTERs rewrite tables / take ACCESS EXCLUSIVE locks. The app engine bakes
in a short statement_timeout (5s) for request safety, which would kill the
rewrite, so this migration raises statement_timeout (and bounds lock waits) for
its own transaction via SET LOCAL.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_card_jsonb_and_fk"
down_revision = "0004_active_model_unique"
branch_labels = None
depends_on = None

_JSONB_COLUMNS: dict[str, tuple[str, ...]] = {
    "cards_raw": (
        "colors",
        "color_identity",
        "color_indicator",
        "keywords",
        "legalities",
        "image_uris",
        "card_faces_json",
        "all_parts",
        "games",
        "finishes",
        "promo_types",
        "frame_effects",
        "prices",
        "multiverse_ids",
    ),
    "card_faces": (
        "color_indicator",
        "image_uris",
    ),
}


def _convert(table: str, columns: tuple[str, ...], target: str, *, inspector: sa.Inspector) -> None:
    """Convert columns to `target` ("JSONB"/"JSON") in a SINGLE ALTER TABLE.

    Postgres rewrites the table once for all ALTER COLUMN clauses in one
    statement, so this is one ACCESS EXCLUSIVE rewrite per table instead of one
    per column — important on the large cards_raw table in production.
    """
    if table not in set(inspector.get_table_names()):
        return
    current_types = {col["name"]: type(col["type"]).__name__.upper() for col in inspector.get_columns(table)}
    to_convert = [c for c in columns if c in current_types and current_types[c] != target]
    if not to_convert:
        return
    clauses = ", ".join(f'ALTER COLUMN "{c}" TYPE {target} USING "{c}"::{target.lower()}' for c in to_convert)
    op.execute(f'ALTER TABLE "{table}" {clauses}')


def _cards_raw_fk_name(inspector: sa.Inspector) -> str | None:
    for fk in inspector.get_foreign_keys("cards"):
        if fk["referred_table"] == "cards_raw" and fk["constrained_columns"] == ["scryfall_id"]:
            return fk["name"]
    return None


def upgrade() -> None:
    bind = op.get_bind()
    # SET LOCAL applies for the remainder of alembic's migration transaction.
    bind.execute(sa.text("SET LOCAL statement_timeout = '600s'"))
    bind.execute(sa.text("SET LOCAL lock_timeout = '30s'"))
    inspector = sa.inspect(bind)

    for table, columns in _JSONB_COLUMNS.items():
        _convert(table, columns, "JSONB", inspector=inspector)

    if "cards" in set(inspector.get_table_names()):
        fk_name = _cards_raw_fk_name(inspector)
        if fk_name is not None:
            op.drop_constraint(fk_name, "cards", type_="foreignkey")
        op.create_foreign_key(
            "fk_cards_scryfall_id_cards_raw",
            "cards",
            "cards_raw",
            ["scryfall_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("SET LOCAL statement_timeout = '600s'"))
    bind.execute(sa.text("SET LOCAL lock_timeout = '30s'"))
    inspector = sa.inspect(bind)

    if "cards" in set(inspector.get_table_names()):
        fk_name = _cards_raw_fk_name(inspector)
        if fk_name is not None:
            op.drop_constraint(fk_name, "cards", type_="foreignkey")
        op.create_foreign_key(
            "fk_cards_scryfall_id_cards_raw",
            "cards",
            "cards_raw",
            ["scryfall_id"],
            ["id"],
        )

    for table, columns in _JSONB_COLUMNS.items():
        _convert(table, columns, "JSON", inspector=inspector)
