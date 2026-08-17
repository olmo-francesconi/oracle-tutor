from __future__ import annotations

import gc
import json
import logging
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from .query_gen import generate_template_queries
from .tag_attribution import DEFAULT_MIN_MARGIN, attribute_tags_to_abilities
from .tag_eval import is_held_out_tag

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
from .train_options import (
    DEFAULT_TRAIN_AUGMENTATION_KEYS,
    TRAIN_AUGMENTATION_LLM_QUERIES,
    TRAIN_AUGMENTATION_TAG_DESCRIPTIONS,
    TRAIN_AUGMENTATION_TAG_PAIRS,
    TRAIN_AUGMENTATION_TEMPLATE_QUERIES,
    parse_train_augmentation_mode,
    serialize_train_augmentation_mode,
)

logger = logging.getLogger("ot_backend.semantic.dataset_service")

TRAINING_DATASET_FILE_NAME = "training-dataset.json"
TRAINING_DATASET_VERSION = 8
TRAINING_BUILD_PAYLOAD_VERSION = 3
_DEFAULT_MAX_TAG_PAIRS_PER_TAG = 150
_DEFAULT_MAX_TAG_PAIR_GROUP_SIZE = 2
_DEFAULT_MAX_TAG_DESC_PAIRS_PER_TAG = 600
FaceIdentity = tuple[str, int]
AbilityIdentity = tuple[str, int, int]
_Identity = TypeVar("_Identity", FaceIdentity, AbilityIdentity)


@dataclass(frozen=True)
class AbilityTextRecord:
    oracle_id: str
    face_ix: int
    ability_ix: int
    name: str
    text: str
    normalized_text: str


@dataclass(frozen=True)
class TrainingDatasetState:
    """The unit of training is an **ability**, not a face.

    At serve time nothing ever embeds a face: `semantic_ability_embeddings` is
    keyed by ability `text_hash`, retrieval probes per ability, and the rerank
    is a Chamfer mean over ability sets. Training on face blobs while serving on
    single abilities was a train/serve mismatch no amount of tag work fixes.
    """

    ability_texts: dict[AbilityIdentity, str]
    pair_ids: list[tuple[AbilityIdentity, AbilityIdentity]]
    direct_text_pairs: list[tuple[str, ...]]
    simcse_examples: int
    tag_pair_examples: int
    tag_desc_pair_examples: int
    template_query_examples: int = 0
    llm_query_examples: int = 0
    card_names: dict[FaceIdentity, str] = field(default_factory=dict)


def _lift_statement_timeout(db: Session) -> None:
    """Dataset builds run minute-long analytics queries. Operator sessions
    inherit the API's 5s statement_timeout (OT_SERVICE_ROLE defaults to "api"),
    which kills them. Disable it for the current build transaction."""
    from sqlalchemy import text

    db.execute(text("SET LOCAL statement_timeout = 0"))


# Hard-negative mining. MultipleNegativesRankingLoss otherwise sees only the
# other examples in the batch as negatives — 31 random cards at batch size 32,
# almost all trivially unrelated, so nothing ever teaches the model where a
# concept STOPS. Cards drawn from tags that co-occur with T are the useful
# contrast: an artifact that "adds multiple mana" but is not a "mana dork" sits
# right on the boundary, which is exactly the distinction we want learned.
_HARD_NEGATIVE_CO_TAGS = 12
_HARD_NEGATIVE_POOL_CAP = 2000
_HARD_NEGATIVE_MEMBER_SAMPLE = 200
_HARD_NEGATIVE_MIN_OVERLAP = 3


def build_hard_negative_pools(
    tag_to_face_ids: Mapping[str, Sequence[_Identity]],
) -> dict[str, list[_Identity]]:
    """Per tag, members that are semantically adjacent but definitively NOT in it.

    Generic over the unit: once tags are attributed to abilities the negative
    for `mana dork` becomes "tap this land: Add one green mana" rather than a
    whole land, which is a far sharper boundary.
    """
    face_to_tags: dict[_Identity, set[str]] = defaultdict(set)
    for tag_name, faces in tag_to_face_ids.items():
        for face_key in faces:
            face_to_tags[face_key].add(tag_name)

    pools: dict[str, list[_Identity]] = {}
    for tag_name, faces in tag_to_face_ids.items():
        members = set(faces)
        co_occurring: Counter[str] = Counter()
        sampled_members = list(members)[:_HARD_NEGATIVE_MEMBER_SAMPLE]
        for face_key in sampled_members:
            for other in face_to_tags[face_key]:
                if other != tag_name:
                    co_occurring[other] += 1

        # Rank by *association*, not raw overlap. Generic tags like
        # "activated ability" (8.8k cards) co-occur with everything, so counting
        # raw overlap draws negatives from a huge unfocused pool. Dividing by the
        # other tag's size prefers tags that are specifically related, which is
        # what makes a negative hard.
        ranked = sorted(
            (
                (count / len(tag_to_face_ids[other]), other)
                for other, count in co_occurring.items()
                if count >= _HARD_NEGATIVE_MIN_OVERLAP and tag_to_face_ids.get(other)
            ),
            reverse=True,
        )

        pool: list[_Identity] = []
        seen: set[_Identity] = set()
        for _score, other in ranked[:_HARD_NEGATIVE_CO_TAGS]:
            for face_key in tag_to_face_ids.get(other, ()):
                if face_key in members or face_key in seen:
                    continue
                seen.add(face_key)
                pool.append(face_key)
                if len(pool) >= _HARD_NEGATIVE_POOL_CAP:
                    break
            if len(pool) >= _HARD_NEGATIVE_POOL_CAP:
                break
        pools[tag_name] = pool
    return pools


def _tag_anchors(tag_name: str, tag_description: str | None) -> list[str]:
    """The anchor texts a tag is taught by.

    Two forms, both emitted. The bare name is what a player actually types
    ("mana dork"); the name-plus-description form carries the meaning for tags
    whose name alone is opaque. Training only on the descriptive form leaves the
    typed query unclaimed, so it lands on whatever else happens to use those
    words — which is how "mana dork" ended up meaning "taps for green mana",
    learned mostly from lands.
    """
    normalized_name = tag_name.replace("-", " ").replace("_", " ").strip()
    anchors = [normalized_name]
    if tag_description:
        described = f"{normalized_name}. {tag_description}".strip()
        if described != normalized_name:
            anchors.append(described)
    return [a for a in anchors if a]


def _distinct_by_text(
    ability_ids: Sequence[AbilityIdentity],
    ability_texts: Mapping[AbilityIdentity, str],
) -> list[AbilityIdentity]:
    """One identity per distinct text, order preserved.

    Ability text deduplicates hard — 63,289 instances collapse to ~37.3k
    distinct, and "Flying." alone is 3,235 of them. Without this a tag whose
    abilities are keywords would spend its whole budget on identical strings,
    and the serve side embeds one vector per distinct text anyway.
    """
    seen: set[str] = set()
    distinct: list[AbilityIdentity] = []
    for ability_id in ability_ids:
        text = ability_texts.get(ability_id) or ""
        if not text.strip() or text in seen:
            continue
        seen.add(text)
        distinct.append(ability_id)
    return distinct


def build_state_from_maps(
    *,
    ability_texts: dict[AbilityIdentity, str],
    card_names: dict[FaceIdentity, str],
    tag_to_ability_ids: dict[str, list[AbilityIdentity]],
    tag_to_anchors: dict[str, list[str]],
    selected_augmentations: set[str],
    max_tag_pairs_per_tag: int = _DEFAULT_MAX_TAG_PAIRS_PER_TAG,
    max_tag_pair_group_size: int = _DEFAULT_MAX_TAG_PAIR_GROUP_SIZE,
    max_tag_desc_pairs_per_tag: int = _DEFAULT_MAX_TAG_DESC_PAIRS_PER_TAG,
    rng: random.Random | None = None,
    llm_pairs: list[tuple[str, str]] | None = None,
) -> TrainingDatasetState:
    """Assemble training examples from already-gathered maps.

    The single source of truth for what a training example *is*. The local
    builder reads the maps from Postgres; the Modal builder reads them from the
    shipped payload and appends LLM-generated pairs it can only produce on a
    GPU. Both then land here, because two copies of this loop drift, and a
    dataset the TUI reports is not the one Modal trains on.

    `tag_to_ability_ids` holds the abilities a tag was *attributed* to — see
    `tag_attribution` — not every ability of every member card.
    """
    rng = rng or random.Random()
    llm_pairs = llm_pairs or []

    distinct_abilities = _distinct_by_text(sorted(ability_texts), ability_texts)
    self_pair_ids = [(ability_id, ability_id) for ability_id in distinct_abilities]

    tag_pair_ids: list[tuple[AbilityIdentity, AbilityIdentity]] = []
    if TRAIN_AUGMENTATION_TAG_PAIRS in selected_augmentations:
        for ability_ids in tag_to_ability_ids.values():
            distinct = _distinct_by_text(ability_ids, ability_texts)
            if len(distinct) < max_tag_pair_group_size:
                continue
            rng.shuffle(distinct)
            for left, right in list(zip(distinct[::2], distinct[1::2], strict=False))[:max_tag_pairs_per_tag]:
                if left[0] != right[0]:
                    tag_pair_ids.append((left, right))

    direct_text_pairs: list[tuple[str, ...]] = []
    if TRAIN_AUGMENTATION_TAG_DESCRIPTIONS in selected_augmentations:
        negative_pools = build_hard_negative_pools(tag_to_ability_ids)
        logger.info(
            "Built hard-negative pools. tags=%d median_pool=%d",
            len(negative_pools),
            sorted(len(v) for v in negative_pools.values())[len(negative_pools) // 2] if negative_pools else 0,
        )
        for tag_name, ability_ids in tag_to_ability_ids.items():
            anchors = tag_to_anchors.get(tag_name) or []
            usable = _distinct_by_text(ability_ids, ability_texts)
            if not usable or not anchors:
                continue
            pool = [a for a in (negative_pools.get(tag_name) or []) if ability_texts.get(a)]
            # Each anchor gets the full budget rather than a share of it. The
            # bare name is the form users actually type, and splitting starved
            # it: "mana dork" fell to 0.085% of the dataset, below the 0.182%
            # the (since-removed) template rule used to give it, and the model
            # stopped ranking mana dorks for it at all.
            for anchor in anchors:
                sampled = list(usable)
                rng.shuffle(sampled)
                for ability_id in sampled[:max_tag_desc_pairs_per_tag]:
                    positive = ability_texts[ability_id]
                    negative = ability_texts[rng.choice(pool)] if pool else None
                    if negative and negative != positive:
                        direct_text_pairs.append((anchor, positive, negative))
                    else:
                        direct_text_pairs.append((anchor, positive))

    template_query_examples = 0
    if TRAIN_AUGMENTATION_TEMPLATE_QUERIES in selected_augmentations:
        for ability_id in distinct_abilities:
            text = ability_texts[ability_id]
            for query in generate_template_queries(text):
                direct_text_pairs.append((query, text))
                template_query_examples += 1

    direct_text_pairs.extend(llm_pairs)

    pair_ids = self_pair_ids + tag_pair_ids
    rng.shuffle(pair_ids)
    rng.shuffle(direct_text_pairs)
    return TrainingDatasetState(
        ability_texts=ability_texts,
        card_names=card_names,
        pair_ids=pair_ids,
        direct_text_pairs=direct_text_pairs,
        simcse_examples=len(self_pair_ids),
        tag_pair_examples=len(tag_pair_ids),
        tag_desc_pair_examples=max(len(direct_text_pairs) - template_query_examples - len(llm_pairs), 0),
        template_query_examples=template_query_examples,
        llm_query_examples=len(llm_pairs),
    )


def _ability_records(db: Session) -> list[AbilityTextRecord]:
    """Every ability, with the normalized text the runtime actually embeds.

    `card_face_abilities.normalized_text` is read rather than re-normalized
    here, so the training text and the served vector come from one string
    produced at ingest time.
    """
    from sqlalchemy import select

    from ..core.models import CardFace, CardFaceAbility

    query = (
        select(
            CardFaceAbility.oracle_id,
            CardFaceAbility.face_ix,
            CardFaceAbility.ability_ix,
            CardFace.name,
            CardFaceAbility.text,
            CardFaceAbility.normalized_text,
        )
        .join(
            CardFace,
            (CardFace.oracle_id == CardFaceAbility.oracle_id) & (CardFace.face_ix == CardFaceAbility.face_ix),
        )
        .order_by(CardFaceAbility.oracle_id, CardFaceAbility.face_ix, CardFaceAbility.ability_ix)
    )
    return [
        AbilityTextRecord(
            oracle_id=oracle_id,
            face_ix=face_ix,
            ability_ix=ability_ix,
            name=name or "",
            text=text or "",
            normalized_text=normalized_text or "",
        )
        for oracle_id, face_ix, ability_ix, name, text, normalized_text in db.execute(query)
    ]


def _gather_tag_maps(
    db: Session,
    ability_texts: dict[AbilityIdentity, str],
    *,
    min_margin: float = DEFAULT_MIN_MARGIN,
) -> tuple[dict[str, list[AbilityIdentity]], dict[str, list[str]]]:
    """Tag membership resolved down to the abilities that justify each tag."""
    from sqlalchemy import select

    from ..core.models import CardTagging, Tag

    card_faces: dict[str, list[FaceIdentity]] = defaultdict(list)
    seen_faces: set[FaceIdentity] = set()
    for oracle_id, face_ix, _ability_ix in ability_texts:
        face_key = (oracle_id, face_ix)
        if face_key not in seen_faces:
            seen_faces.add(face_key)
            card_faces[oracle_id].append(face_key)

    tag_members: dict[str, list[FaceIdentity]] = defaultdict(list)
    tag_descriptions: dict[str, str | None] = {}
    rows = db.execute(
        select(CardTagging.card_id, Tag.tag_name, Tag.tag_description)
        .join(Tag, CardTagging.tag_id == Tag.id)
        .filter(CardTagging.foreign_key == "oracleId")
        .filter(Tag.tag_namespace == "card")
    )
    for card_id, tag_name, tag_description in rows:
        # Held-out tags are the evaluation set. Training on them would turn the
        # eval into a memorisation test — see semantic/tag_eval.py.
        if is_held_out_tag(tag_name):
            continue
        tag_descriptions[tag_name] = tag_description
        tag_members[tag_name].extend(card_faces.get(card_id, ()))

    attributed = attribute_tags_to_abilities(
        ability_texts, tag_members, tag_descriptions, min_margin=min_margin
    )
    tag_to_ability_ids = {name: ids for name, ids in attributed.items() if ids}
    tag_to_anchors = {
        name: _tag_anchors(name, tag_descriptions.get(name)) for name in tag_to_ability_ids
    }
    return tag_to_ability_ids, tag_to_anchors


def build_training_dataset_state(
    db: Session,
    *,
    augmentation_mode: str | None = None,
    max_tag_pairs_per_tag: int = _DEFAULT_MAX_TAG_PAIRS_PER_TAG,
    max_tag_pair_group_size: int = _DEFAULT_MAX_TAG_PAIR_GROUP_SIZE,
    max_tag_desc_pairs_per_tag: int = _DEFAULT_MAX_TAG_DESC_PAIRS_PER_TAG,
) -> TrainingDatasetState:
    selected_augmentations = set(
        parse_train_augmentation_mode(augmentation_mode)
        if augmentation_mode is not None
        else DEFAULT_TRAIN_AUGMENTATION_KEYS
    )
    _lift_statement_timeout(db)
    logger.info("Loading ability text for semantic training.")
    ability_records = _ability_records(db)
    ability_texts: dict[AbilityIdentity, str] = {}
    card_names: dict[FaceIdentity, str] = {}
    for ability in ability_records:
        ability_texts[(ability.oracle_id, ability.face_ix, ability.ability_ix)] = ability.normalized_text
        card_names[(ability.oracle_id, ability.face_ix)] = ability.name

    logger.info("Attributing tags to abilities.")
    tag_to_ability_ids, tag_to_anchors = _gather_tag_maps(db, ability_texts)

    return build_state_from_maps(
        ability_texts=ability_texts,
        card_names=card_names,
        tag_to_ability_ids=tag_to_ability_ids,
        tag_to_anchors=tag_to_anchors,
        selected_augmentations=selected_augmentations,
        max_tag_pairs_per_tag=max_tag_pairs_per_tag,
        max_tag_pair_group_size=max_tag_pair_group_size,
        max_tag_desc_pairs_per_tag=max_tag_desc_pairs_per_tag,
    )


def build_training_dataset_build_payload(
    db: Session,
    *,
    augmentation_mode: str | None = None,
    max_tag_pairs_per_tag: int = _DEFAULT_MAX_TAG_PAIRS_PER_TAG,
    max_tag_pair_group_size: int = _DEFAULT_MAX_TAG_PAIR_GROUP_SIZE,
    max_tag_desc_pairs_per_tag: int = _DEFAULT_MAX_TAG_DESC_PAIRS_PER_TAG,
) -> dict[str, Any]:
    from .semantic_state import build_training_dataset_metadata

    selected_augmentations = tuple(
        parse_train_augmentation_mode(augmentation_mode)
        if augmentation_mode is not None
        else DEFAULT_TRAIN_AUGMENTATION_KEYS
    )
    _lift_statement_timeout(db)
    ability_records = _ability_records(db)
    ability_texts: dict[AbilityIdentity, str] = {}
    ability_payload_rows: list[dict[str, Any]] = []
    card_name_rows: list[dict[str, Any]] = []
    seen_faces: set[FaceIdentity] = set()
    for ability in ability_records:
        ability_texts[(ability.oracle_id, ability.face_ix, ability.ability_ix)] = ability.normalized_text
        ability_payload_rows.append(
            {
                "oracle_id": ability.oracle_id,
                "face_ix": ability.face_ix,
                "ability_ix": ability.ability_ix,
                "raw": ability.text,
                "text": ability.normalized_text,
            }
        )
        face_key = (ability.oracle_id, ability.face_ix)
        if face_key not in seen_faces:
            seen_faces.add(face_key)
            card_name_rows.append(
                {"oracle_id": ability.oracle_id, "face_ix": ability.face_ix, "name": ability.name}
            )

    # Attribution runs here, once, and ships its result: it needs corpus-wide
    # token frequencies the remote side would otherwise have to recompute, and
    # keeping the algorithm on one side of the wire keeps it testable locally.
    tag_to_ability_ids, tag_to_anchors = _gather_tag_maps(db, ability_texts)

    return {
        "version": TRAINING_BUILD_PAYLOAD_VERSION,
        "augmentation_mode": serialize_train_augmentation_mode(selected_augmentations),
        "options": {
            "max_tag_pairs_per_tag": max_tag_pairs_per_tag,
            "max_tag_pair_group_size": max_tag_pair_group_size,
            "max_tag_desc_pairs_per_tag": max_tag_desc_pairs_per_tag,
        },
        "features": {
            "tag_pairs": TRAIN_AUGMENTATION_TAG_PAIRS in selected_augmentations,
            "tag_descriptions": TRAIN_AUGMENTATION_TAG_DESCRIPTIONS in selected_augmentations,
            "template_queries": TRAIN_AUGMENTATION_TEMPLATE_QUERIES in selected_augmentations,
            "llm_queries": TRAIN_AUGMENTATION_LLM_QUERIES in selected_augmentations,
        },
        "abilities": ability_payload_rows,
        "card_names": card_name_rows,
        "tag_to_ability_ids": {
            tag_name: [list(ability_id) for ability_id in ability_ids]
            for tag_name, ability_ids in sorted(tag_to_ability_ids.items())
        },
        "tag_to_desc": dict(sorted(tag_to_anchors.items())),
        "metadata": build_training_dataset_metadata(db),
    }


def build_training_dataset_payload(
    dataset_state: TrainingDatasetState,
    *,
    metadata: dict[str, object] | None = None,
) -> dict[str, Any]:
    return {
        "version": TRAINING_DATASET_VERSION,
        "ability_texts": [
            {"oracle_id": oracle_id, "face_ix": face_ix, "ability_ix": ability_ix, "text": text}
            for (oracle_id, face_ix, ability_ix), text in sorted(dataset_state.ability_texts.items())
        ],
        # Kept out of the ability rows: one name per face, not per ability.
        "card_names": [
            {"oracle_id": oracle_id, "face_ix": face_ix, "name": name}
            for (oracle_id, face_ix), name in sorted(dataset_state.card_names.items())
        ],
        "pair_ids": [
            [list(left), list(right)] for left, right in dataset_state.pair_ids
        ],
        "direct_text_pairs": list(dataset_state.direct_text_pairs),
        "simcse_examples": dataset_state.simcse_examples,
        "tag_pair_examples": dataset_state.tag_pair_examples,
        "tag_desc_pair_examples": dataset_state.tag_desc_pair_examples,
        "template_query_examples": dataset_state.template_query_examples,
        "llm_query_examples": dataset_state.llm_query_examples,
        "metadata": metadata or {},
    }


def serialize_training_dataset(
    dataset_state: TrainingDatasetState,
    *,
    metadata: dict[str, object] | None = None,
) -> bytes:
    return json.dumps(build_training_dataset_payload(dataset_state, metadata=metadata)).encode("utf-8")


def export_training_dataset(
    dataset_state: TrainingDatasetState,
    output_path: Path,
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(serialize_training_dataset(dataset_state, metadata=metadata))


def load_training_dataset_payload(input_path: Path) -> dict[str, Any]:
    return json.loads(input_path.read_text(encoding="utf-8"))


def load_training_dataset_payload_bytes(dataset_bytes: bytes) -> dict[str, Any]:
    return json.loads(dataset_bytes.decode("utf-8"))


def load_training_dataset_metadata(input_path: Path) -> dict[str, object]:
    payload = load_training_dataset_payload(input_path)
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        return {}
    return {str(key): value for key, value in metadata.items()}


def _as_ability_id(row: Sequence[Any]) -> AbilityIdentity:
    """Accept both the 2-element face keys of v2-v7 and the 3-element v8 keys."""
    oracle_id, face_ix = str(row[0]), int(row[1])
    return (oracle_id, face_ix, int(row[2]) if len(row) > 2 else 0)


def _training_dataset_state_from_payload(payload: dict[str, Any]) -> TrainingDatasetState:
    version = int(payload["version"])
    if version not in (2, 3, 4, 5, 6, 7, 8):
        raise ValueError(f"Unsupported training dataset format version: {version}.")

    if version >= 8:
        ability_texts = {
            (str(r["oracle_id"]), int(r["face_ix"]), int(r["ability_ix"])): str(r["text"])
            for r in payload["ability_texts"]
        }
        card_names = {
            (str(r["oracle_id"]), int(r["face_ix"])): str(r["name"])
            for r in payload.get("card_names", [])
            if r.get("name")
        }
    else:
        # Versions 2-7 trained on whole faces. Reading each face as a single
        # unit reproduces those datasets exactly, so an archived one still
        # retrains rather than becoming unloadable.
        ability_texts = {
            (str(r["oracle_id"]), int(r["face_ix"]), 0): str(r["text"])
            for r in payload["face_texts"]
        }
        card_names = {
            (str(r["oracle_id"]), int(r["face_ix"])): str(r["name"])
            for r in payload["face_texts"]
            if r.get("name")
        }

    pair_ids = [
        (_as_ability_id(left), _as_ability_id(right)) for left, right in payload["pair_ids"]
    ]
    # 2-tuples (anchor, positive) and 3-tuples (anchor, positive, hard negative).
    direct_text_pairs: list[tuple[str, ...]] = [tuple(str(x) for x in row) for row in payload.get("direct_text_pairs", [])]
    return TrainingDatasetState(
        ability_texts=ability_texts,
        card_names=card_names,
        pair_ids=pair_ids,
        direct_text_pairs=direct_text_pairs,
        simcse_examples=int(payload["simcse_examples"]),
        tag_pair_examples=int(payload["tag_pair_examples"]),
        tag_desc_pair_examples=int(payload.get("tag_desc_pair_examples", 0)),
        template_query_examples=int(payload.get("template_query_examples", 0)),
        llm_query_examples=int(payload.get("llm_query_examples", 0)),
    )


def load_training_dataset(input_path: Path) -> TrainingDatasetState:
    return _training_dataset_state_from_payload(load_training_dataset_payload(input_path))


def load_training_dataset_bytes(dataset_bytes: bytes) -> TrainingDatasetState:
    return _training_dataset_state_from_payload(load_training_dataset_payload_bytes(dataset_bytes))


def prepare_and_save_dataset(
    output_path: Path,
    *,
    augmentation_mode: str | None = None,
    max_tag_pairs_per_tag: int = _DEFAULT_MAX_TAG_PAIRS_PER_TAG,
    max_tag_pair_group_size: int = _DEFAULT_MAX_TAG_PAIR_GROUP_SIZE,
    max_tag_desc_pairs_per_tag: int = _DEFAULT_MAX_TAG_DESC_PAIRS_PER_TAG,
) -> TrainingDatasetState:
    from ..core.database import SessionLocal
    from .semantic_state import build_training_dataset_metadata

    db = SessionLocal()
    try:
        dataset_state = build_training_dataset_state(
            db,
            augmentation_mode=augmentation_mode,
            max_tag_pairs_per_tag=max_tag_pairs_per_tag,
            max_tag_pair_group_size=max_tag_pair_group_size,
            max_tag_desc_pairs_per_tag=max_tag_desc_pairs_per_tag,
        )
        dataset_metadata = build_training_dataset_metadata(db)
    finally:
        db.close()
    export_training_dataset(dataset_state, output_path, metadata=dataset_metadata)
    logger.info("Released in-memory dataset state after export.")
    gc.collect()
    return dataset_state


def export_training_dataset_bytes(*, augmentation_mode: str | None = None) -> bytes:
    from ..core.database import SessionLocal
    from .semantic_state import build_training_dataset_metadata

    db = SessionLocal()
    try:
        dataset_state = build_training_dataset_state(db, augmentation_mode=augmentation_mode)
        dataset_metadata = build_training_dataset_metadata(db)
    finally:
        db.close()
    return serialize_training_dataset(dataset_state, metadata=dataset_metadata)


def export_training_build_payload_bytes(*, augmentation_mode: str | None = None) -> bytes:
    from ..core.database import SessionLocal

    db = SessionLocal()
    try:
        payload = build_training_dataset_build_payload(db, augmentation_mode=augmentation_mode)
    finally:
        db.close()
    return json.dumps(payload).encode("utf-8")
