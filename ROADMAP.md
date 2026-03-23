# Roadmap: Oracle Tutor

## Vision
The go-to search tool for MTG players — fast, accurate card discovery by name, text, and similarity, with a polished frontend experience.

## Milestones
- [ ] Embedding-based semantic search (pgvector) as an alternative to TF-IDF
- [ ] Advanced filters (color identity, CMC, card type, format legality)
- [ ] Saved searches / collections (user accounts)
- [ ] Mobile-optimized UI
- [ ] Public API with rate limiting and docs

## Completed
- [x] TF-IDF search over Scryfall bulk data (v1.0)
- [x] EDHREC ranking integration (v1.1)
- [x] Similar-cards endpoint (v1.2)
- [x] Subprocess TF-IDF rebuild to avoid RSS step-up (v1.4)
- [x] Railway production deployment with daily worker cron (v1.4)
