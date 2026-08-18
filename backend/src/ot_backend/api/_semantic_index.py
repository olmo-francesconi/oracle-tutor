from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Callable, Protocol, cast

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    # Type-only: this module exists so the API degrades gracefully when the
    # semantic extras are missing, so nothing from `semantic.index` may be
    # imported at runtime outside the guarded block below.
    from ..semantic.index import SimilarityHit

try:
    from ..semantic.index import get_semantic_index as get_semantic_index_fn
except ImportError:
    get_semantic_index_fn = None  # type: ignore[assignment]


class SemanticIndexProtocol(Protocol):
    model_id: str | None

    def warm(self, db: Session) -> None: ...

    def similar_to_face(
        self,
        face_key: tuple[str, int],
        limit: int,
        db: Session,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
        include_abilities: Sequence[int] | None = None,
        exclude_abilities: Sequence[int] | None = None,
    ) -> list[SimilarityHit]: ...

    def search_oracle(
        self,
        query: str,
        limit: int,
        db: Session,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[SimilarityHit]: ...


def get_semantic_index() -> SemanticIndexProtocol | None:
    if get_semantic_index_fn is None:
        return None
    return cast(Callable[[], SemanticIndexProtocol | None], get_semantic_index_fn)()

