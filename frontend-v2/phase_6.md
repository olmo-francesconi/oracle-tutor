# Phase 6 Implementation Plan

## Goal

Make the SPA linkable without pulling the app into a heavier routing architecture too early.

## Scope

Included:

- lightweight URL syncing
- History API updates
- direct-link behavior for search state

Explicitly excluded:

- card selection in the URL
- `/card/:id`
- filter params for now

Deferred decision:

- whether `/card/:id` can be introduced cleanly without adopting router complexity

## Implementation Shape

Likely files:

- `src/lib/urlState.ts`
- small integration in `SearchShell`

Possible URL support:

- `?q=...`
- restore submitted query on initial load

## Constraints

- do not adopt React Router unless the value is clear
- do not distort the shell architecture just to support a route
- keep URL syncing additive to current state, not a new source of truth

## Acceptance Criteria

Phase 6 is complete when:

- searches can be linked directly
- reload restores the intended search state
- the implementation remains lightweight

## Validation

Required checks:

- `cd frontend-v2 && npm run build`
- `cd frontend-v2 && npm run lint`

Manual checks:

- copy/paste a search URL
- reload the page
- confirm state restoration

## Commit Plan

Docs commit:

- `docs: phase 6 implementation plan`

Implementation commit:

- `feat: add frontend v2 url state`
