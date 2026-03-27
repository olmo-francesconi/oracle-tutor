# Phase 5 Implementation Plan

## Goal

Add a focused card overlay without turning it into another application mode.

## Scope

Included:

- card overlay
- optional detail fetch
- close behavior
- symbol-rich card header

Conditional:

- next/prev navigation only if it stays simple

## Implementation Shape

Files:

- `src/components/CardOverlay.tsx`

Behavior:

- open from selected card state
- close back to results
- keep routing concerns out

## Constraints

- the overlay should not become a second app shell
- avoid unnecessary internal state
- fetch more detail only if the results payload is insufficient

## Acceptance Criteria

Phase 5 is complete when:

- card inspection works
- the overlay feels integrated with the results flow
- the implementation remains isolated and small

## Validation

Required checks:

- `cd frontend-v2 && npm run build`
- `cd frontend-v2 && npm run lint`

Manual checks:

- open a card
- close a card
- confirm symbol-heavy header content renders correctly

## Commit Plan

Docs commit:

- `docs: phase 5 implementation plan`

Implementation commit:

- `feat: add frontend v2 card overlay`
