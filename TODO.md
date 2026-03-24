# TODO: Oracle Tutor

## Current focus
Semantic-only API migration on `semantic-api` branch — schema refactor (cards_raw, oracle_id PK, Alembic) merged in. Next: finish removing the fuzzy fallback and unify all search through pgvector.

## Up next
- [ ] Remove fuzzy name-search fallback; route `/search` entirely through semantic index
- [ ] Add `.env.example` for local dev onboarding
- [ ] Apply server-side filtering in semantic endpoints (color identity, CMC, type, format legality)
- [ ] Wire `cards_raw` data into card detail API response (set info, prices, image URIs per printing)
- [ ] Confirm Railway Cron schedule and worker token rotation process

## Blocked
<!-- Anything waiting on external input -->
