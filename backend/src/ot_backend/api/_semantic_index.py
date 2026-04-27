from __future__ import annotations

from typing import Callable, Protocol, cast

from sqlalchemy.orm import Session

try:
    from ..semantic.index import get_semantic_index as _get_semantic_index_fn
except ImportError:
    _get_semantic_index_fn = None  # type: ignore[assignment]


class SemanticIndexProtocol(Protocol):
    model_id: str | None

    def warm(self) -> None: ...

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
    ) -> list[tuple[tuple[str, int], float]]: ...

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
    ) -> list[tuple[tuple[str, int], float]]: ...


def _get_semantic_index() -> SemanticIndexProtocol | None:
    if _get_semantic_index_fn is None:
        return None
    return cast(Callable[[], SemanticIndexProtocol | None], _get_semantic_index_fn)()

