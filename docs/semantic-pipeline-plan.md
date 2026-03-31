# Semantic Pipeline Improvement Plan

## Background

The search engine has gone through three model approaches. Each solved some problems while introducing others:

| Approach | Strengths | Failures |
|---|---|---|
| TF-IDF | Exact keyword match | Huge vocabulary matrix in memory; no semantic generalisation |
| Word2Vec | Fast, length-invariant similarity, decent short keyword queries | Little semantic knowledge; "punish drawing" ≠ "opponent draws a card" |
| SBERT (current) | True semantic understanding; concept queries work well when long | Short queries are noisy; many obviously-relevant cards ranked low |

The current SBERT setup is not fundamentally broken — the architecture and infrastructure are sound. The problem is a specific, diagnosable mismatch between how the model was trained and how it is used at query time.

---

## Root Cause: Training/Inference Distribution Mismatch

### What the model learned

Every training pair in the current dataset is **oracle↔oracle** — two long, normalized MTG card texts on both sides of the pair:

- SimCSE self-pairs: `(oracle_text, oracle_text)` — card paired with itself
- Tag pairs: `(oracle_text_A, oracle_text_B)` — two cards sharing a tag
- Tag-description pairs: `(tag_name + description, oracle_text)` — slightly asymmetric, but tag descriptions are still formal multi-word phrases

The model learned: *"these two long structured texts describe similar mechanics"*.

### What happens at query time

A user types `"draw cards"`. This two-word string is embedded by a model calibrated for document-document similarity. The resulting vector sits in a region of the embedding space that has never been seen on either side of a training pair.

SBERT encodes the **full sequence meaning**. A 2-word query and a 50-word oracle text produce embeddings that are structurally very different — the 2-word embedding is underspecified and volatile, meaning small phrasing differences cause large cosine distance swings. This is the **asymmetric search problem**.

Word2Vec did not have this problem because averaging word vectors is length-invariant by construction: a 2-word average and a 50-word average both live in the same vector space with the same expected norm behaviour. But Word2Vec has no contextual or semantic knowledge beyond the training corpus.

### Why long queries improve results

A query like `"punish opponents for drawing cards by making them discard"` starts to resemble oracle text in length and structure. The model is implicitly entering familiar territory, so cosine similarity becomes more reliable.

### Secondary issue: weak negatives

4,000 tag-based pairs with random non-matching cards as negatives is a thin training signal. Random negatives are too easy — the model never has to learn to distinguish cards that are *mechanically close but not the same*. Hard negatives (cards that partially share mechanics but shouldn't rank highly for a given query) would sharpen decision boundaries considerably.

---

## Proposed Solution: Asymmetric Fine-tuning via Synthetic Query Generation

The fix keeps SBERT and the existing infrastructure. It adds short, user-intent-style text to the **left side of training pairs**, so the model sees query-document pairs during training instead of only document-document pairs.

This technique underlies production passage retrieval models (e.g. `msmarco-MiniLM`, `msmarco-distilbert`). The difference is that theirs used human-generated query logs; ours will use generated synthetic queries.

The existing `direct_text_pairs: list[tuple[str, str]]` field in `TrainingDatasetState` already supports arbitrary (text_A, text_B) pairs, so no changes to the training loop are required. The fix is purely in the dataset construction step.

---

## Implementation Plan

### Step 1 — Template-based query generation (free, deterministic)

**Goal:** Generate 3–5 short user-intent queries per card face from the already-normalized oracle text. These go directly into `direct_text_pairs`.

**Why templates first:** MTG oracle text uses a highly constrained, structured grammar. A large fraction of mechanics can be captured by deterministic pattern extraction without any model. This is zero-cost, fast to iterate on, and produces consistent results.

**Challenges:**

- The oracle text is already normalized (mana symbols expanded, card name replaced with "this card"). Templates must match the normalized form, not the raw form.
  - Raw: `{T}: Add {G}.` → Normalized: `tap this card. pay tap this card: one green mana.`
  - Templates must pattern-match on the normalized version.
- MTG has hundreds of distinct keywords and ability words. Template coverage will be incomplete — that is fine. Uncovered cards fall back to oracle-only pairs, which is no worse than the current state.
- Query phrasing must feel like a real user query, not a re-statement of oracle text. `"tap for green mana"` is good; `"pay tap this card one green mana"` is not.

**Approach:**

Implement a `generate_template_queries(normalized_text: str) -> list[str]` function in a new file `backend/src/ot_backend/embed/query_gen.py`. It should:

1. Run a small set of regex patterns over the normalized oracle text
2. For each matched pattern, produce 1–3 short query strings
3. Return the full list (may be empty if no pattern fires)

Example pattern groups to cover (not exhaustive):

| Pattern in normalized text | Generated queries |
|---|---|
| `"draw a card"` or `"draw two cards"` | `"draw a card"`, `"card draw"`, `"draw cards effect"` |
| `"draw cards at the beginning"` | `"draw cards each turn"`, `"repeatable draw"` |
| `"discard"` | `"discard cards"`, `"hand disruption"` |
| `"destroy target creature"` | `"destroy creature"`, `"creature removal"` |
| `"exile target"` | `"exile removal"`, `"exile spell"` |
| `"tap this card: ... mana"` | `"mana dork"`, `"tap for mana"`, `"mana production"` |
| `"add ... mana"` | `"mana ramp"`, `"mana acceleration"` |
| `"counter target spell"` | `"counterspell"`, `"counter a spell"`, `"spell denial"` |
| `"return ... to ... hand"` | `"bounce effect"`, `"return to hand"` |
| `"create a ... token"` | `"token creation"`, `"make tokens"` |
| `"whenever ... dies"` | `"death trigger"`, `"creature dies trigger"` |
| `"+1/+1 counter"` | `"put counters"`, `"grow counters"`, `"strengthen creature"` |
| `"flying"` | `"flying creature"`, `"evasion"` |
| `"trample"` | `"trample"`, `"combat damage through blockers"` |
| `"lifelink"` | `"lifelink"`, `"gain life on attack"` |
| `"haste"` | `"haste"`, `"attack immediately"` |

**Integration:** In `build_training_dataset_state`, after the existing pair construction, call `generate_template_queries` for every face text and append `(query, oracle_text)` pairs to `direct_text_pairs`. Cap per-card at 5 queries to avoid over-representing any single card.

**Expected scale:** ~30k card faces × 2–4 matching patterns average × 1–2 queries each ≈ 60k–120k new `direct_text_pairs`. This is a 15–30× increase in asymmetric training signal.

---

### Step 2 — LLM-based query augmentation via Modal (quality coverage for complex text)

**Goal:** For cards where template patterns fire on fewer than 2 queries (complex oracle text, modal spells, rules-heavy cards), use an LLM to generate natural language queries.

**Why LLM for the remainder:** Complex MTG text like `"Whenever an opponent casts their second spell each turn, draw a card"` has no obvious template match for the trigger condition. A language model can produce `"draw when opponent plays multiple spells"`, which is genuinely useful.

**Why Modal and not local Ollama:** 30k cards × inference time on a MacBook M-chip is feasible but slow for an iteration cycle. Modal on T4 GPU with a 7B model runs in minutes. Locally, this is a multi-hour job.

**Model choice:** `mistral:7b` or `llama3:8b` via Ollama on a Modal container, or HuggingFace hosted inference with `FLAN-T5-large` (free tier, smaller but faster). FLAN-T5 is specifically trained for instruction following and handles `"generate a search query for this card text"` prompts well.

**Challenges:**

- LLM output is non-deterministic. The same card may produce different queries across runs — this is a feature (diversity), not a bug, but the dataset should be generated once and committed to `training-dataset.json` so training is reproducible.
- LLM may produce queries that are too long (starts resembling oracle text again) or too specific (names specific card names). Need a post-filter: drop queries over 12 words, drop queries containing proper nouns that appear in the card name.
- Cost: HuggingFace free tier has rate limits. Modal compute on T4 is ~$0.80/hr; a full 30k card run at batch size 32 should complete in under 30 minutes.

**Integration:** Add a new Modal function `generate_queries` to `scripts/modal_train.py` (or a new `scripts/modal_query_gen.py`) that accepts the `face_texts` dict from the exported training dataset JSON and returns a `query_augmentations.json` mapping `(oracle_id, face_ix) → [query, ...]`. The pipeline then merges this file into `direct_text_pairs` at dataset construction time.

The pipeline already reads from a pre-exported `training-dataset.json`. A simple extension: add a `--query-augmentations` path argument to `pipeline.py` that, if provided, merges the augmentation file into `direct_text_pairs` before training.

---

### Step 3 — Hard negative mining

**Goal:** Sharpen model decision boundaries by adding pairs of cards that are superficially similar but should not match a given query.

**Why this matters:** `MultipleNegativesRankingLoss` currently uses in-batch random negatives. With batch size 64 this gives 63 negatives per example — decent coverage, but all negatives are random. A card about `"draw three cards at end of turn"` will rarely be paired in-batch with `"draw a card at the beginning of your upkeep"`, yet these are the confusing cases the model most needs to discriminate.

**Approach:**

1. After training a first model (or using the current model), run all oracle embeddings through it and build a cosine similarity index.
2. For each card, retrieve its top-20 nearest neighbours.
3. Filter to pairs where similarity is in the 0.70–0.85 range — high enough to be confusing, low enough to be wrong.
4. Tag-check: if the two cards share no tags, the high-similarity pair is a candidate hard negative.
5. Add these as explicit negatives. Note: `MultipleNegativesRankingLoss` does not support explicit negatives natively. Two options:
   - Use `TripletLoss(anchor, positive, hard_negative)` for the hard negative subset
   - Use `MultipleNegativesRankingLoss` but construct batches so hard negatives appear in the same batch as their anchor

**Timing:** Step 3 is lower priority than Steps 1 and 2. It requires a trained model as input (bootstrap from current model). Run it as a second training pass after Step 1 shows improvement.

---

## Evaluation

Before and after each step, measure quality against a small hand-curated query set:

| Query | Expected top-3 |
|---|---|
| `"draw a card"` | Ancestral Recall, Brainstorm, Opt |
| `"destroy target creature"` | Terror, Murder, Doom Blade |
| `"tap for green mana"` | Llanowar Elves, Birds of Paradise, Elvish Mystic |
| `"punish opponents for drawing cards"` | Underworld Dreams, Nekusar, Runeflare Trap |
| `"make lots of tokens"` | Goblin Rabblemaster, Increasing Devotion, Martial Coup |
| `"counter a spell"` | Counterspell, Force of Will, Mana Leak |
| `"gain life"` | Healing Salve, Soul Warden, Blessed Sanctuary |

Store this as a `backend/scripts/eval_queries.json` file. Add a `--eval` flag to the pipeline that prints cosine similarity scores for the curated set after training, so regressions are visible immediately.

---

## What Changes and What Doesn't

| Component | Changes | Notes |
|---|---|---|
| `text_prep.py` | None | Template queries must match normalized text |
| `pipeline.py` | New `--query-augmentations` arg; minor change to `build_training_dataset_state` | Additive only |
| `modal_train.py` | Optional: new `generate_queries` function | Can be a separate script |
| `embed/query_gen.py` | New file | Template-based query generator |
| `scripts/modal_query_gen.py` | New file | LLM-based query generator (Step 2) |
| Training loop / loss function | None | `MultipleNegativesRankingLoss` stays |
| ONNX export / inference | None | |
| `index.py` (query-time) | None | |
| DB schema | None | |

The key architectural constraint is that query-time encoding must use the **same normalization** as training-time. The current pipeline already ensures this (both sides call `normalize_oracle_text`). The same function must also be applied to user queries at inference time — this is already happening via `text_prep.py`.

The normalization implication for template queries: since normalized text has card names replaced with `"this card"`, mana symbols expanded to words, and numbers converted to words, template patterns must target the normalized form. For example, a draw pattern should match `"draw a card"` (already present verbatim in normalized text), not `"Draw a card"` or `"{draw}"`.

---

## Open Questions

1. **How many tags exist, and what is the coverage?** If tags cover 80%+ of cards, the tag-description pairs already provide reasonable asymmetry and Step 1 templates may be enough. If tags cover less than 50% of cards, Step 2 LLM augmentation becomes more important.

2. **What is the right cap on synthetic queries per card?** Too many queries for a heavily-tagged card will cause that card's oracle text to appear frequently as a positive, potentially overfitting the model to well-tagged cards.

3. **Should template queries be applied to the query at inference time as well?** Probably not — users type what they type. The goal is to move the *model's* embedding space, not to rewrite queries. Query expansion is a separate technique and would add inference latency.

4. **Is `all-MiniLM-L6-v2` the right base model?** It is a symmetric similarity model. A passage retrieval base like `msmarco-MiniLM-L6-v2` is pre-trained for asymmetric query-document tasks and may converge faster with the new training data. Worth a comparison run.
