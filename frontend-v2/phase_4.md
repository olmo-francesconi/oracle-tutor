# Phase 4 Implementation Plan

## Goal

Render results simply and support infinite scroll.

## Scope

Included:

- `ResultsGrid`
- result cards
- infinite scroll
- real `searchOracleText` integration

Excluded:

- elaborate result bucketing unless clearly necessary
- heavy internal result component state
- card detail UI
- route work
- filter UI beyond preserving state shape

## Implementation Shape

Files:

- `src/components/ResultsGrid.tsx`
- `src/components/CardImage.tsx` only if a dedicated image wrapper stays small
- small card helpers only if they remove duplication

State ownership:

- parent owns data, loading state, and pagination
- grid mainly renders props

## Infinite Scroll Plan

Start simple:

- use an intersection sentinel
- fetch next page when needed
- keep behavior explicit

Avoid:

- virtualization in the first version
- grid-owned query logic

## Acceptance Criteria

Phase 4 is complete when:

- submitted searches render real results
- infinite scroll loads more results reliably
- the shell remains the only data owner
- the grid code stays mostly dumb

## Validation

Required checks:

- `cd frontend-v2 && npm run build`
- `cd frontend-v2 && npm run lint`

Manual checks:

- run a search
- scroll to load more
- confirm results append correctly

## Commit Plan

Docs commit:

- `docs: phase 4 implementation plan`

Implementation commit:

- `feat: add frontend v2 results grid`
