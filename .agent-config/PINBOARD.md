# Pinboard

Shared communication board between the orchestrator (Claude) and Codex workers.

---

## Active Tasks

### Feature: Semantic Search API (SBERT + pgvector)

**Branch:** `semantic-api` (branch off `develop`)

**Goal:** Add a parallel semantic search layer alongside the existing TF-IDF system. New endpoints mirror the existing ones but use Sentence-BERT embeddings stored in pgvector for similarity. At the end, a comparison test harness prints TF-IDF vs semantic results side-by-side.

**Do not touch** the existing TF-IDF pipeline, endpoints, or tests. All new code goes in new files or clearly delimited new sections.

---

#### Step 1 — Create the branch

```bash
git checkout -b semantic-api develop
```

---

#### Step 2 — Add dependencies

Edit `api/pyproject.toml`.

Add `pgvector>=0.3` to the base `[project.dependencies]` list (needed at API runtime).

Add a new optional group:
```toml
[project.optional-dependencies]
semantic = [
  "sentence-transformers>=3.0",
  "pgvector>=0.3",
]
```

---

#### Step 3 — Database: new tables

Edit `api/src/oracle_tutor_api/core/models.py`.

**3a.** Add import at the top:
```python
from pgvector.sqlalchemy import Vector
```

**3b.** Add `CardTag` model:
```python
class CardTag(Base):
    __tablename__ = "card_tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True, nullable=False)
    tag: Mapped[str] = mapped_column(nullable=False)

    card: Mapped["Card"] = relationship(back_populates="tags")
```

Add reverse relationship to the existing `Card` model:
```python
tags: Mapped[List["CardTag"]] = relationship(back_populates="card", cascade="all, delete-orphan")
```

**3c.** Add `CardFaceSemanticEmbedding` model:
```python
class CardFaceSemanticEmbedding(Base):
    __tablename__ = "card_face_semantic_embeddings"

    face_id: Mapped[int] = mapped_column(ForeignKey("card_faces.id"), primary_key=True)
    embedding: Mapped[Vector] = mapped_column(Vector(384), nullable=False)

    face: Mapped["CardFace"] = relationship(back_populates="semantic_embedding")
```

Add reverse relationship to the existing `CardFace` model:
```python
semantic_embedding: Mapped[Optional["CardFaceSemanticEmbedding"]] = relationship(
    back_populates="face", uselist=False, cascade="all, delete-orphan"
)
```

The existing `Base.metadata.create_all(engine)` call will create these tables automatically on next startup — no migration script needed.

---

#### Step 4 — Scryfall tag ingestion

Create: `api/src/oracle_tutor_api/worker/fetch_tags.py`

**Important:** First probe the Scryfall tagger endpoint for one card before implementing the full fetch. The undocumented endpoint is:
```
GET https://tagger.scryfall.com/card/{set_code}/{collector_number}/tags
```
If it returns non-200 or is inaccessible, fall back to using the official `keywords` array already present in Scryfall bulk card JSON (already ingested — query it from the `card_faces` table if stored, or re-read from `api/data/`).

Full implementation:
```python
import time
import requests
from sqlalchemy.orm import Session
from oracle_tutor_api.core.models import Card, CardTag

TAGGER_URL = "https://tagger.scryfall.com/card/{set_code}/{number}/tags"
RATE_LIMIT_SLEEP = 0.1  # 100ms between requests per Scryfall policy


def fetch_and_store_tags(
    db: Session, scryfall_set: str, collector_number: str, card_id: str
) -> None:
    resp = requests.get(
        TAGGER_URL.format(set_code=scryfall_set, number=collector_number), timeout=10
    )
    if resp.status_code != 200:
        return
    tags = resp.json()  # inspect actual response shape and adjust field name below
    db.query(CardTag).filter_by(card_id=card_id).delete()
    for tag in tags:
        db.add(CardTag(card_id=card_id, tag=tag["name"]))  # adjust "name" to actual field
    db.commit()
    time.sleep(RATE_LIMIT_SLEEP)


def run_fetch_tags(db: Session) -> None:
    """Fetch tags for all cards. Call this from the worker after card ingestion."""
    cards = db.query(Card).all()
    for card in cards:
        # scryfall_set and collector_number must be available on the Card model
        # or sourced from the bulk data stored in api/data/
        fetch_and_store_tags(db, card.scryfall_set, card.collector_number, card.id)
```

If `scryfall_set` / `collector_number` are not currently on the `Card` model, add them as nullable string columns and populate during the existing worker ingestion step.

---

#### Step 5 — Text normalization

Create: `api/src/oracle_tutor_api/semantic/text_prep.py`

Port `normalize_oracle_text()` from the deckmind project at:
`/Users/olmo/Desktop/dev/deckmind/packages/deckmind-oracle2vec/src/deckmind_oracle2vec/oracle_text.py`

Copy that file's logic verbatim, removing deckmind-specific imports and making it standalone. Keep the same function signature:

```python
def normalize_oracle_text(
    text: str,
    card_name: str = "",
    type_line: str = "",
    keep_reminder_text: bool = False,
) -> str:
    ...
```

Also add this wrapper (used by both training and inference):
```python
from oracle_tutor_api.core.models import CardFace

def face_to_text(face: CardFace) -> str:
    return normalize_oracle_text(
        text=face.oracle_text or "",
        card_name=face.name or "",
        type_line=face.type_line or "",
    )
```

---

#### Step 6 — Training pipeline

Create: `api/src/oracle_tutor_api/semantic/train.py`

Runnable as `python -m oracle_tutor_api.semantic.train`.

Two training signals are combined into one training run with `MultipleNegativesRankingLoss`.

**Signal 1 — SimCSE (unsupervised):** pass the same oracle text twice as a pair. SBERT's dropout produces two slightly different representations, which become the positive pair. No external labels needed.

**Signal 2 — Scryfall tag pairs (supervised):** two card faces that share at least one community tag are a positive pair.

```python
import os
import random
from collections import defaultdict
from torch.utils.data import DataLoader
from sentence_transformers import SentenceTransformer, InputExample, losses

from oracle_tutor_api.core.db import SessionLocal
from oracle_tutor_api.core.models import CardFace, CardTag
from oracle_tutor_api.semantic.text_prep import face_to_text

MODEL_OUT = os.environ.get("SEMANTIC_MODEL_PATH", "data/semantic/model")


def build_training_examples(db):
    faces = db.query(CardFace).all()
    face_texts = {f.id: face_to_text(f) for f in faces}

    # Signal 1: SimCSE
    simcse = [
        InputExample(texts=[t, t])
        for t in face_texts.values()
        if t.strip()
    ]

    # Signal 2: tag pairs
    tag_to_face_ids = defaultdict(list)
    face_card_map = {f.id: f.card_id for f in faces}
    card_face_map = defaultdict(list)
    for f in faces:
        card_face_map[f.card_id].append(f.id)

    for tag in db.query(CardTag).all():
        for fid in card_face_map.get(tag.card_id, []):
            if fid in face_texts:
                tag_to_face_ids[tag.tag].append(fid)

    tag_pairs = []
    for fids in tag_to_face_ids.values():
        if len(fids) < 2:
            continue
        random.shuffle(fids)
        for a, b in list(zip(fids[::2], fids[1::2]))[:50]:
            if face_texts.get(a) and face_texts.get(b):
                tag_pairs.append(InputExample(texts=[face_texts[a], face_texts[b]]))

    all_examples = simcse + tag_pairs
    random.shuffle(all_examples)
    return all_examples


def main():
    db = SessionLocal()
    try:
        examples = build_training_examples(db)
    finally:
        db.close()

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    dataloader = DataLoader(examples, shuffle=True, batch_size=64)
    loss = losses.MultipleNegativesRankingLoss(model)

    model.fit(
        train_objectives=[(dataloader, loss)],
        epochs=5,
        warmup_steps=max(100, len(examples) // 20),
        show_progress_bar=True,
    )
    os.makedirs(MODEL_OUT, exist_ok=True)
    model.save(MODEL_OUT)
    print(f"Model saved to {MODEL_OUT}")


if __name__ == "__main__":
    main()
```

---

#### Step 7 — Compute and store embeddings

Create: `api/src/oracle_tutor_api/semantic/compute.py`

Runnable as `python -m oracle_tutor_api.semantic.compute`.

```python
import os
from sentence_transformers import SentenceTransformer
from oracle_tutor_api.core.db import SessionLocal
from oracle_tutor_api.core.models import CardFace, CardFaceSemanticEmbedding
from oracle_tutor_api.semantic.text_prep import face_to_text

MODEL_PATH = os.environ.get("SEMANTIC_MODEL_PATH", "data/semantic/model")
BATCH_SIZE = 256


def compute_and_store(db) -> None:
    model = SentenceTransformer(MODEL_PATH)
    faces = db.query(CardFace).all()
    texts = [face_to_text(f) for f in faces]

    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    db.query(CardFaceSemanticEmbedding).delete()
    for face, emb in zip(faces, embeddings):
        db.add(CardFaceSemanticEmbedding(face_id=face.id, embedding=emb.tolist()))
    db.commit()
    print(f"Stored {len(faces)} embeddings.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        compute_and_store(db)
    finally:
        db.close()
```

---

#### Step 8 — Runtime query index

Create: `api/src/oracle_tutor_api/semantic/index.py`

Loaded as a singleton at API startup (analogous to `tfidf_index.py`).

```python
import os
from typing import List, Optional, Tuple
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session
from oracle_tutor_api.core.models import CardFaceSemanticEmbedding
from oracle_tutor_api.semantic.text_prep import normalize_oracle_text

MODEL_PATH = os.environ.get("SEMANTIC_MODEL_PATH", "data/semantic/model")

_index: Optional["SemanticIndex"] = None


class SemanticIndex:
    def __init__(self, model_path: str = MODEL_PATH):
        self.model = SentenceTransformer(model_path)

    def encode_query(self, text: str) -> list:
        normalized = normalize_oracle_text(text)
        return self.model.encode([normalized], normalize_embeddings=True)[0].tolist()

    def similar_to_face(
        self, face_id: int, limit: int, db: Session
    ) -> List[Tuple[int, float]]:
        seed = db.get(CardFaceSemanticEmbedding, face_id)
        if seed is None:
            return []
        return self._pgvector_query(seed.embedding, limit + 1, db, exclude=face_id)

    def search_oracle(
        self, query: str, limit: int, db: Session
    ) -> List[Tuple[int, float]]:
        return self._pgvector_query(self.encode_query(query), limit, db)

    def _pgvector_query(
        self,
        query_vec,
        limit: int,
        db: Session,
        exclude: Optional[int] = None,
    ) -> List[Tuple[int, float]]:
        dist = CardFaceSemanticEmbedding.embedding.cosine_distance(query_vec).label("distance")
        q = (
            db.query(CardFaceSemanticEmbedding.face_id, dist)
            .order_by(dist)
            .limit(limit)
        )
        if exclude is not None:
            q = q.filter(CardFaceSemanticEmbedding.face_id != exclude)
        # cosine distance ∈ [0, 2]; convert to similarity ∈ [-1, 1]
        return [(row.face_id, round(1.0 - row.distance, 6)) for row in q.all()]


def get_semantic_index() -> Optional[SemanticIndex]:
    global _index
    if _index is None and os.path.exists(MODEL_PATH):
        _index = SemanticIndex()
    return _index
```

---

#### Step 9 — API router + mount

**Create:** `api/src/oracle_tutor_api/api/semantic_router.py`

Reuse the existing `SimilarCard` response model from `main.py` (import it).

```python
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from oracle_tutor_api.core.db import get_db
from oracle_tutor_api.core.models import CardFace
from oracle_tutor_api.semantic.index import get_semantic_index
from oracle_tutor_api.api.main import SimilarCard  # adjust if model is moved to a shared module

router = APIRouter(prefix="/semantic", tags=["semantic"])


def _to_similar_cards(results: list, db: Session) -> List[SimilarCard]:
    out = []
    for face_id, sim in results:
        face = db.get(CardFace, face_id)
        if face is None:
            continue
        card = face.card
        out.append(SimilarCard(
            id=str(face_id),
            name=face.name or "",
            card_name=card.name or "",
            similarity=sim,
            rank=card.edhrec_rank,
            type_line=face.type_line,
            mana_cost=face.mana_cost,
            oracle_text=face.oracle_text,
            power=face.power,
            toughness=face.toughness,
            colors=face.colors,
            layout=card.layout,
            rarity=card.rarity,
            legalities=card.legalities,
        ))
    return out


@router.get("/similar-cards/{card_id}", response_model=List[SimilarCard])
def semantic_similar_cards(
    card_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    index = get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")
    face = db.query(CardFace).filter(CardFace.card_id == card_id).first()
    if face is None:
        raise HTTPException(status_code=404, detail="Card not found")
    results = index.similar_to_face(face.id, limit=limit + offset, db=db)
    return _to_similar_cards(results[offset:], db)


@router.get("/search-oracle", response_model=List[SimilarCard])
def semantic_search_oracle(
    q: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    index = get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")
    results = index.search_oracle(q, limit=limit + offset, db=db)
    return _to_similar_cards(results[offset:], db)
```

**Edit `api/src/oracle_tutor_api/api/main.py`** — add these two lines in the appropriate places:

```python
# near other imports at the top:
from oracle_tutor_api.api.semantic_router import router as semantic_router

# after app is created and before routes are registered:
app.include_router(semantic_router)
```

Also in the startup event (where TF-IDF is built), add:
```python
from oracle_tutor_api.semantic.index import get_semantic_index
get_semantic_index()  # no-op if model file not present yet
```

---

#### Step 10 — Semantic worker Dockerfile + docker-compose service

**Create:** `api/Dockerfile.semantic-worker`

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY api/ .

RUN pip install uv && uv pip install --system ".[semantic,worker]"

CMD ["sh", "-c", "python -m oracle_tutor_api.semantic.train && python -m oracle_tutor_api.semantic.compute"]
```

**Edit `docker-compose.yml`** — add this service:

```yaml
semantic-worker:
  build:
    context: .
    dockerfile: api/Dockerfile.semantic-worker
  depends_on:
    db:
      condition: service_healthy
  volumes:
    - ./api/data:/app/data
  environment:
    DATABASE_URL: postgresql+psycopg://postgres:postgres@db:5432/oracle_tutor
    SEMANTIC_MODEL_PATH: /app/data/semantic/model
  restart: "no"
```

---

#### Step 11 — Comparison test harness

Create: `api/tests/test_semantic_vs_tfidf.py`

This is a qualitative comparison tool, not a correctness test. Run with `pytest api/tests/test_semantic_vs_tfidf.py -s` against a running local API.

```python
"""
Qualitative comparison between TF-IDF and semantic search endpoints.
Run with: pytest api/tests/test_semantic_vs_tfidf.py -s
Requires a running API at localhost:8000 with both indexes loaded.
"""
import pytest
from httpx import Client

BASE_URL = "http://localhost:8000"

QUERY_TEXTS = [
    "flying deathtouch",
    "draw cards when a creature dies",
    "ramp search basic land",
    "destroy target creature",
    "counter target spell",
    "proliferate counters",
    "deal damage to any target",
]


@pytest.fixture(scope="module")
def client():
    return Client(base_url=BASE_URL, timeout=30)


@pytest.mark.parametrize("query", QUERY_TEXTS)
def test_compare_search_oracle(client, query):
    tfidf = client.get("/search-oracle", params={"q": query, "limit": 10})
    semantic = client.get("/semantic/search-oracle", params={"q": query, "limit": 10})

    assert tfidf.status_code == 200, f"TF-IDF failed: {tfidf.text}"
    assert semantic.status_code == 200, f"Semantic failed: {semantic.text}"

    tf_results = tfidf.json()
    sem_results = semantic.json()

    print(f"\n{'='*90}")
    print(f"Query: '{query}'")
    print(f"{'Rank':<5} {'TF-IDF':<35} {'Score':<8} | {'Semantic':<35} {'Score':<8}")
    print(f"{'-'*90}")
    for i, (t, s) in enumerate(zip(tf_results, sem_results), 1):
        print(
            f"{i:<5} {t['name']:<35} {t['similarity']:<8.4f} | "
            f"{s['name']:<35} {s['similarity']:<8.4f}"
        )
```

---

#### Step 12 — Update project docs

Edit `ROADMAP.md`: mark "Embedding-based semantic search (pgvector)" as in progress.

Edit `TODO.md`: set current focus to:
> `semantic-api` branch — SBERT fine-tuning pipeline (SimCSE + Scryfall tags) + pgvector endpoints + TF-IDF comparison harness

---

## Worker Status

<!-- Workers append their status here on start and completion -->

---

## Completed Work

<!-- Orchestrator moves completed tasks here after validation -->

---

## Notes & Decisions

- Model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim), fine-tuned in-repo
- Training: SimCSE (unsupervised, oracle text) + Scryfall tag pairs (supervised)
- Storage: fine-tuned model saved to `api/data/semantic/model/` (filesystem volume)
- Embeddings: L2-normalized 384-dim vectors in `card_face_semantic_embeddings` (pgvector)
- New endpoints are additive — existing TF-IDF endpoints and tests are untouched
- Scryfall community tagger API access must be probed before full tag fetch implementation; fallback to bulk data `keywords` field if inaccessible
