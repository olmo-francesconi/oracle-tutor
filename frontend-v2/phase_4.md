# Phase 4 Implementation Plan

## Goal

Render results simply and support infinite scroll.

## Scope

Included:

- `ResultsGrid`
- result cards
- infinite scroll
- selection wiring

Excluded:

- elaborate result bucketing unless clearly necessary
- heavy internal result component state

## Implementation Shape

Files:

- `src/components/ResultsGrid.tsx`
- supporting card tile component only if needed

State ownership:

- parent owns data and selection
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
- selection state can open a card
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
