"""Flag bare keyword abilities on card_face_abilities.

Keywords are deliberately NOT removed from the ability layer:

* 502 faces (~1.5%) are keyword-only — Flying-vanilla creatures — and would end
  up with zero abilities, dropping out of the index entirely.
* Searching "flying" would return nothing.
* They cost almost nothing to keep: keywords are 652 of ~37.4k distinct ability
  texts (1.7%), because they dedupe by text hash.

Instead they are flagged, so retrieval can exclude them on request
(`ignore_keywords`) while IDF weighting de-emphasises them by default.

Backfill sets the flag from the same catalog the ingest uses, so existing rows
do not need a re-ingest.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from ot_backend.semantic.ability_split import _REMINDER, _is_keyword_ability

revision = "0007_ability_keyword_flag"
down_revision = "0006_ability_layer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001_initial_schema's Base.metadata.create_all() already creates this
    # column on a fresh database (same guard as 0002/0003/0006).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "is_keyword" not in {col["name"] for col in inspector.get_columns("card_face_abilities")}:
        op.add_column(
            "card_face_abilities",
            sa.Column("is_keyword", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    # Backfill through the SAME predicate the ingest uses, rather than a SQL
    # re-implementation. An earlier SQL version silently disagreed on ~2k rows
    # (it stripped only one trailing symbol, so "Foretell {1}{U}" and
    # "Suspend 2—{1}{W}" were missed), which would have made a later re-ingest
    # quietly change which abilities count as keywords.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT oracle_id, face_ix, ability_ix, text FROM card_face_abilities")
    ).all()
    keyword_keys = [
        {"o": oracle_id, "f": face_ix, "a": ability_ix}
        for oracle_id, face_ix, ability_ix, text in rows
        if _is_keyword_ability(_REMINDER.sub("", text or ""))
    ]
    if keyword_keys:
        bind.execute(
            sa.text(
                "UPDATE card_face_abilities SET is_keyword = true "
                "WHERE oracle_id = :o AND face_ix = :f AND ability_ix = :a"
            ),
            keyword_keys,
        )
    if "ix_card_face_abilities_is_keyword" not in {
        idx["name"] for idx in inspector.get_indexes("card_face_abilities")
    }:
        op.create_index(
            "ix_card_face_abilities_is_keyword",
            "card_face_abilities",
            ["is_keyword"],
        )


def downgrade() -> None:
    op.drop_index("ix_card_face_abilities_is_keyword", table_name="card_face_abilities")
    op.drop_column("card_face_abilities", "is_keyword")
