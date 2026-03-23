# Roadmap: Oracle Tutor

## Vision
The go-to search tool for MTG players — fast, accurate card discovery by name, text, and semantic similarity, with a polished frontend experience.

## Milestones

### Up next
- [ ] Semantic-only API (remove fuzzy fallback, unify search surface)
- [ ] Advanced filters applied server-side (color identity, CMC, card type, format legality)
- [ ] `.env.example` for local dev onboarding
- [ ] Public API with rate limiting and docs

### Future
- [ ] Saved searches / collections (user accounts)

## Completed
- [x] Basic card search over Scryfall bulk data (v1.0)
- [x] Semantic Oracle-text search with pgvector embeddings (v1.1)
- [x] Similar-cards endpoint (v1.1)
- [x] Mobile-optimized UI with bottom bar, drawers, overlay navigation (v1.2)
- [x] Railway production deployment with daily ingest worker cron (v1.3)
- [x] API performance: HNSW index, schema-ready cache, N+1 fix, TTL cache, pool tuning (v1.4)
- [x] Switch inference from sentence-transformers to ONNX Runtime (v1.4)
