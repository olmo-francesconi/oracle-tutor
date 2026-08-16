from __future__ import annotations

import gc
import json
import logging
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .query_gen import generate_template_queries
from .text_prep import normalize_oracle_text

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
TRAINING_DATASET_VERSION = 6
TRAINING_BUILD_PAYLOAD_VERSION = 2
_DEFAULT_MAX_TAG_PAIRS_PER_TAG = 150
_DEFAULT_MAX_TAG_PAIR_GROUP_SIZE = 2
_DEFAULT_MAX_TAG_DESC_PAIRS_PER_TAG = 300
FaceIdentity = tuple[str, int]


@dataclass(frozen=True)
class FaceTextRecord:
    oracle_id: str
    face_ix: int
    name: str
    type_line: str
    oracle_text: str


@dataclass(frozen=True)
class TrainingDatasetState:
    face_texts: dict[FaceIdentity, str]
    pair_ids: list[tuple[FaceIdentity, FaceIdentity]]
    direct_text_pairs: list[tuple[str, str]]
    simcse_examples: int
    tag_pair_examples: int
    tag_desc_pair_examples: int
    template_query_examples: int = 0
    llm_query_examples: int = 0
    face_names: dict[FaceIdentity, str] = field(default_factory=dict)


def _lift_statement_timeout(db: Session) -> None:
    """Dataset builds run minute-long analytics queries. Operator sessions
    inherit the API's 5s statement_timeout (OT_SERVICE_ROLE defaults to "api"),
    which kills them. Disable it for the current build transaction."""
    from sqlalchemy import text

    db.execute(text("SET LOCAL statement_timeout = 0"))


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


def _face_text_records(db: Session) -> list[FaceTextRecord]:
    from sqlalchemy import select

    from ..core.models import CardFace

    records: list[FaceTextRecord] = []
    query = select(
        CardFace.oracle_id,
        CardFace.face_ix,
        CardFace.name,
        CardFace.type_line,
        CardFace.oracle_text,
    ).order_by(CardFace.oracle_id, CardFace.face_ix)
    for oracle_id, face_ix, name, type_line, oracle_text in db.execute(query):
        records.append(
            FaceTextRecord(
                oracle_id=oracle_id,
                face_ix=face_ix,
                name=name or "",
                type_line=type_line or "",
                oracle_text=oracle_text or "",
            )
        )
    return records


def _normalize_face_record(face: FaceTextRecord) -> str:
    return normalize_oracle_text(text=face.oracle_text, card_name=face.name, type_line=face.type_line)


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
    logger.info("Loading face text for semantic training.")
    face_records = _face_text_records(db)
    face_texts: dict[FaceIdentity, str] = {}
    face_names: dict[FaceIdentity, str] = {}
    card_face_map: dict[str, list[FaceIdentity]] = defaultdict(list)
    for face in face_records:
        face_key = (face.oracle_id, face.face_ix)
        face_texts[face_key] = _normalize_face_record(face)
        face_names[face_key] = face.name
        card_face_map[face.oracle_id].append((face.oracle_id, face.face_ix))

    self_pair_ids = [(face_key, face_key) for face_key, text in face_texts.items() if text.strip()]

    try:
        from sqlalchemy import select

        from ..core.models import CardTagging, Tag
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Tag models are unavailable in the current codebase state.") from exc

    logger.info("Building tag-derived positive pairs.")
    tag_to_face_ids: dict[str, list[FaceIdentity]] = defaultdict(list)
    tag_to_anchors: dict[str, list[str]] = {}
    tag_to_desc_faces: dict[str, list[FaceIdentity]] = defaultdict(list)

    direct_oracle_taggings = db.execute(
        select(CardTagging.card_id, Tag.tag_name, Tag.tag_description)
        .join(Tag, CardTagging.tag_id == Tag.id)
        .filter(CardTagging.foreign_key == "oracleId")
        .filter(Tag.tag_namespace == "card")
    )
    for card_id, tag_name, tag_description in direct_oracle_taggings:
        face_keys = [fk for fk in card_face_map.get(card_id, []) if fk in face_texts]
        for face_key in face_keys:
            tag_to_face_ids[tag_name].append(face_key)
        tag_to_anchors[tag_name] = _tag_anchors(tag_name, tag_description)
        for face_key in face_keys:
            tag_to_desc_faces[tag_name].append(face_key)

    tag_pair_ids: list[tuple[FaceIdentity, FaceIdentity]] = []
    if TRAIN_AUGMENTATION_TAG_PAIRS in selected_augmentations:
        for fids in tag_to_face_ids.values():
            if len(fids) < max_tag_pair_group_size:
                continue
            random.shuffle(fids)
            for a, b in list(zip(fids[::2], fids[1::2]))[:max_tag_pairs_per_tag]:
                if a[0] != b[0] and face_texts.get(a) and face_texts.get(b):
                    tag_pair_ids.append((a, b))

    logger.info("Building tag-description anchor pairs.")
    direct_text_pairs: list[tuple[str, str]] = []
    if TRAIN_AUGMENTATION_TAG_DESCRIPTIONS in selected_augmentations:
        for tag_name, face_ids in tag_to_desc_faces.items():
            anchors = tag_to_anchors.get(tag_name) or []
            if not face_ids or not anchors:
                continue
            # The cap is a per-tag budget shared across anchors, so teaching the
            # bare name too does not double this augmentation's share.
            per_anchor = max(1, max_tag_desc_pairs_per_tag // len(anchors))
            for anchor in anchors:
                sampled = random.sample(face_ids, min(len(face_ids), per_anchor))
                for face_key in sampled:
                    direct_text_pairs.append((anchor, face_texts[face_key]))

    logger.info("Building template query pairs.")
    template_query_examples = 0
    if TRAIN_AUGMENTATION_TEMPLATE_QUERIES in selected_augmentations:
        for face_key, oracle_text in face_texts.items():
            for query in generate_template_queries(oracle_text):
                direct_text_pairs.append((query, oracle_text))
                template_query_examples += 1
    logger.info("Template query pairs built. count=%d", template_query_examples)

    pair_ids = self_pair_ids + tag_pair_ids
    random.shuffle(pair_ids)
    random.shuffle(direct_text_pairs)
    tag_desc_count = len(direct_text_pairs) - template_query_examples
    return TrainingDatasetState(
        face_texts=face_texts,
        face_names=face_names,
        pair_ids=pair_ids,
        direct_text_pairs=direct_text_pairs,
        simcse_examples=len(self_pair_ids),
        tag_pair_examples=len(tag_pair_ids),
        tag_desc_pair_examples=tag_desc_count,
        template_query_examples=template_query_examples,
        llm_query_examples=0,
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
    face_records = _face_text_records(db)
    face_payload_rows: list[dict[str, Any]] = []
    card_face_map: dict[str, list[FaceIdentity]] = defaultdict(list)
    for face in face_records:
        face_key = (face.oracle_id, face.face_ix)
        face_payload_rows.append(
            {
                "oracle_id": face.oracle_id,
                "face_ix": face.face_ix,
                "name": face.name,
                "type_line": face.type_line,
                "oracle_text": face.oracle_text,
                "text": _normalize_face_record(face),
            }
        )
        card_face_map[face.oracle_id].append(face_key)

    try:
        from sqlalchemy import select

        from ..core.models import CardTagging, Tag
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Tag models are unavailable in the current codebase state.") from exc

    tag_to_face_ids: dict[str, list[FaceIdentity]] = defaultdict(list)
    tag_to_desc: dict[str, list[str]] = {}
    tag_to_desc_faces: dict[str, list[FaceIdentity]] = defaultdict(list)

    direct_oracle_taggings = db.execute(
        select(CardTagging.card_id, Tag.tag_name, Tag.tag_description)
        .join(Tag, CardTagging.tag_id == Tag.id)
        .filter(CardTagging.foreign_key == "oracleId")
        .filter(Tag.tag_namespace == "card")
    )
    for card_id, tag_name, tag_description in direct_oracle_taggings:
        face_keys = card_face_map.get(card_id, [])
        for face_key in face_keys:
            tag_to_face_ids[tag_name].append(face_key)
            tag_to_desc_faces[tag_name].append(face_key)
        tag_to_desc[tag_name] = _tag_anchors(tag_name, tag_description)

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
        "faces": face_payload_rows,
        "tag_to_face_ids": {
            tag_name: [[oracle_id, face_ix] for oracle_id, face_ix in face_ids]
            for tag_name, face_ids in sorted(tag_to_face_ids.items())
        },
        "tag_to_desc": dict(sorted(tag_to_desc.items())),
        "tag_to_desc_faces": {
            tag_name: [[oracle_id, face_ix] for oracle_id, face_ix in face_ids]
            for tag_name, face_ids in sorted(tag_to_desc_faces.items())
        },
        "metadata": build_training_dataset_metadata(db),
    }


def build_training_dataset_payload(
    dataset_state: TrainingDatasetState,
    *,
    metadata: dict[str, object] | None = None,
) -> dict[str, Any]:
    return {
        "version": TRAINING_DATASET_VERSION,
        "face_texts": [
            {
                "oracle_id": oracle_id,
                "face_ix": face_ix,
                "text": text,
                **({"name": dataset_state.face_names[(oracle_id, face_ix)]} if (oracle_id, face_ix) in dataset_state.face_names else {}),
            }
            for (oracle_id, face_ix), text in sorted(dataset_state.face_texts.items())
        ],
        "pair_ids": [
            [[left_oracle_id, left_face_ix], [right_oracle_id, right_face_ix]]
            for (left_oracle_id, left_face_ix), (right_oracle_id, right_face_ix) in dataset_state.pair_ids
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


def _training_dataset_state_from_payload(payload: dict[str, Any]) -> TrainingDatasetState:
    version = int(payload["version"])
    if version not in (2, 3, 4, 5, 6):
        raise ValueError(f"Unsupported training dataset format version: {version}.")
    face_texts = {
        (str(r["oracle_id"]), int(r["face_ix"])): str(r["text"])
        for r in payload["face_texts"]
    }
    face_names = {
        (str(r["oracle_id"]), int(r["face_ix"])): str(r["name"])
        for r in payload["face_texts"]
        if r.get("name")
    }
    pair_ids = [
        ((str(left_oracle_id), int(left_face_ix)), (str(right_oracle_id), int(right_face_ix)))
        for [left_oracle_id, left_face_ix], [right_oracle_id, right_face_ix] in payload["pair_ids"]
    ]
    direct_text_pairs: list[tuple[str, str]] = [(str(a), str(b)) for a, b in payload.get("direct_text_pairs", [])]
    return TrainingDatasetState(
        face_texts=face_texts,
        face_names=face_names,
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
