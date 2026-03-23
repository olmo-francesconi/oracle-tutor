from __future__ import annotations

import logging
import os
import random
from collections import defaultdict
from importlib import import_module
from pathlib import Path
from typing import Any

from ..core.database import SessionLocal
from ..core.models import CardFace
from .text_prep import face_to_text

logger = logging.getLogger("ot_backend.embed.train")

MODEL_OUT = os.environ.get("SEMANTIC_MODEL_PATH", "data/semantic/model")
BASE_MODEL_NAME = os.environ.get("SEMANTIC_BASE_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
BATCH_SIZE = 64
EPOCHS = 5
MIN_WARMUP_STEPS = 100
WARMUP_DIVISOR = 20
MAX_TAG_PAIRS_PER_TAG = 50
MAX_TAG_PAIR_GROUP_SIZE = 2


def _load_sentence_transformers() -> tuple[Any, Any, Any]:
    try:
        sentence_transformers = import_module("sentence_transformers")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "sentence-transformers is required for semantic training. "
            "Install the optional semantic extra before running this module."
        ) from exc
    return (
        getattr(sentence_transformers, "SentenceTransformer"),
        getattr(sentence_transformers, "InputExample"),
        getattr(sentence_transformers, "losses"),
    )


def build_training_examples(db, input_example_cls: Any) -> list[Any]:
    faces = db.query(CardFace).all()
    face_texts = {f.id: face_to_text(f) for f in faces}

    simcse = [input_example_cls(texts=[t, t]) for t in face_texts.values() if t.strip()]

    card_face_map: dict[str, list[int]] = defaultdict(list)
    for face in faces:
        card_face_map[face.card_id].append(face.id)

    tag_to_face_ids: dict[str, list[int]] = defaultdict(list)
    try:
        from ..core.models import CardTagging, Tag
    except Exception as exc:  # pragma: no cover - current branch safety
        raise RuntimeError("Tag models are unavailable in the current codebase state.") from exc

    direct_oracle_taggings = (
        db.query(CardTagging, Tag)
        .join(Tag, CardTagging.tag_id == Tag.id)
        .filter(CardTagging.foreign_key == "oracleId")
        .filter(Tag.tag_namespace == "card")
        .all()
    )
    for card_tagging, tag in direct_oracle_taggings:
        for fid in card_face_map.get(card_tagging.card_id, []):
            if fid in face_texts:
                tag_to_face_ids[tag.tag_name].append(fid)

    tag_pairs: list[Any] = []
    for fids in tag_to_face_ids.values():
        if len(fids) < MAX_TAG_PAIR_GROUP_SIZE:
            continue
        random.shuffle(fids)
        for a, b in list(zip(fids[::2], fids[1::2]))[:MAX_TAG_PAIRS_PER_TAG]:
            if face_texts.get(a) and face_texts.get(b):
                tag_pairs.append(input_example_cls(texts=[face_texts[a], face_texts[b]]))

    examples = simcse + tag_pairs
    random.shuffle(examples)
    return examples


def main() -> int:
    SentenceTransformer, InputExample, losses = _load_sentence_transformers()

    db = SessionLocal()
    try:
        examples = build_training_examples(db, InputExample)
    finally:
        db.close()

    if not examples:
        logger.error("No semantic training examples found; nothing to train.")
        return 1

    model = SentenceTransformer(BASE_MODEL_NAME)

    try:
        torch_utils_data = import_module("torch.utils.data")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError("torch is required for semantic training.") from exc
    DataLoader = getattr(torch_utils_data, "DataLoader")

    dataloader = DataLoader(examples, shuffle=True, batch_size=BATCH_SIZE)
    loss = losses.MultipleNegativesRankingLoss(model)

    warmup_steps = max(MIN_WARMUP_STEPS, len(examples) // WARMUP_DIVISOR)
    logger.info(
        "Training semantic model. examples=%d epochs=%d batch_size=%d warmup_steps=%d",
        len(examples),
        EPOCHS,
        BATCH_SIZE,
        warmup_steps,
    )

    model.fit(
        train_objectives=[(dataloader, loss)],
        epochs=EPOCHS,
        warmup_steps=warmup_steps,
        show_progress_bar=True,
    )

    output_path = Path(MODEL_OUT)
    output_path.mkdir(parents=True, exist_ok=True)
    model.save(str(output_path))
    logger.info("Semantic model saved to %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
