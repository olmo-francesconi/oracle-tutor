# Oracle Tutor — Roadmap

This document captures the intended evolution of the project: what to build, why, and rough ordering. It is opinionated — not just a wishlist.

---

## In progress

### Semantic search as the primary surface
Route free-text intent queries through `/similar-cards?q=` so users can describe what a card does and get meaningful results. The name autocomplete remains for exact lookups. The real work here is the UX (see below).

### Wire `cards_raw` into card detail
`/card/{oracle_id}` currently returns oracle-level data only. Pull in `cards_raw` to expose per-printing image URIs on the card detail page. **Printings are aesthetic — this is purely for display quality, not a search concern.**

### `.env.example`
The only variable needed for local development is `DB_PASSWORD` (required during the embedding training step). One file, two lines, zero friction.

---

## Near-term

### UX redesign — unified search box

The current two-box design (card name input + oracle input) is technically correct but awkward. Users should not have to choose a search mode.

**Proposed direction: one search box, split-pane dropdown.**

- **Top section — name matches**: fast ILIKE results, appear immediately on keystroke. Familiar autocomplete behaviour.
- **Bottom section — semantic matches**: debounced, labelled distinctly (e.g. "cards about…"). Hits `/similar-cards?q=` with a short delay so it doesn't race the name results.

The box does not need a mode toggle. Query shape implies intent: "Brainstorm" is a card name, "draw cards for free" is a semantic query. Both work in the same input. When the query clearly matches a card name, name results dominate. When it reads like a description, semantic results surface naturally.

This removes the cognitive overhead of choosing a search mode and collapses two inputs into one clean surface. The rest of the UI (filters, results grid, card detail) likely needs a revisit alongside this — but the search box is the right place to start.

### Model tracking with MLflow

Training already works (`embed/pipeline.py`), but there is no way to compare runs, track hyperparameters, or know which model is deployed. MLflow is the obvious move.

Beyond tracking, the model artifacts should not live on disk in production. The right path is:
- MLflow model registry for versioning and promotion (staging → production)
- Artifacts stored in object storage (S3-compatible), not the container filesystem
- API pulls the active production model at startup rather than reading a local path

This is the infrastructure work that makes fine-tuning a repeatable process rather than a one-off.

### Deck synergy via co-play data

"Similar cards" (embedding proximity) is a poor deck-building signal — it finds cards that read alike, not cards that work together. What actually matters for deck-building is co-occurrence: which cards are frequently played in the same decks.

There is already a piece of code that computes this. The integration path is:
1. Ingest co-play frequency data (EDHREC or similar) into a new table
2. Expose a `/synergistic-cards` endpoint that ranks by co-occurrence score, optionally filtered by format and color identity
3. Surface this in the UI as a distinct mode from semantic similarity

This is a more honest deck-building tool than the current similar-cards feature.

---

## Medium-term

### Price indicators on results

`cards_raw` has Scryfall price data. A simple $-$$$ scale on each result card in the grid is low implementation cost and high practical value — especially combined with semantic search ("budget ramp spells for green").

A price range filter on `/similar-cards` would pair naturally with this.

### Format legality filtering

Already a filter param on `/similar-cards`. The remaining work is UX: a prominent format picker that persists across searches, not a buried filter option.

### Collection-scoped search

Let users paste or import a decklist/collection and scope all results to cards they own. Requires some client-side state management (collection stored locally, sent as a filter) and likely a small backend change to accept an allowlist of `oracle_id`s. Needs infrastructure thought before implementation.

---

## Longer-term

### Card relationship graph view

`card_relationships` table exists. A visual graph of how cards relate to each other (by embedding proximity, shared tags, co-play frequency) would be a genuinely novel interface. High complexity, high ceiling. Worth prototyping once the data sources (co-play, tags) are solid.

### Deck critique

Given a decklist, identify semantic and mechanical gaps: missing interaction, curve problems, colour imbalance. This requires aggregating embeddings over a card set and reasoning about the result. Interesting ML problem but needs more infrastructure and compute than currently available. Revisit after model tracking is in place.

---

## Deliberately out of scope (for now)

- **Multiple printings as a search concern** — printings differ aesthetically; oracle text is what matters for rules and search. Card detail can show printing images, but search operates on oracle data only.
- **Public API** — not a priority until the core product is stable.
- **Social / sharing features** — out of scope until the single-user experience is excellent.
