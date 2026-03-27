# Phase 1 Implementation Plan

## Goal

Establish the minimal application shell and top-level state model.

## Scope

Included:

- create a single `SearchShell`
- keep home and results as two states of one app
- define top-level state in one place
- create a simple visual transition between home and results

Excluded:

- real API calls
- full search box logic
- overlay logic

## Implementation Shape

Main files:

- `src/App.tsx`
- `src/app/SearchShell.tsx`
- `src/types/ui.ts`

Core state:

- `draftQuery`
- `submittedQuery`
- `filters`
- `results`
- `hasMore`
- `isLoading`
- `isLoadingMore`
- `selectedCard`

Derived state:

- `isHome`
- `isResults`

## UI Plan

Render:

- a home hero state when `submittedQuery` is null
- a results state when `submittedQuery` exists
- one shared top-level shell

The first version can use placeholder content.

## Acceptance Criteria

Phase 1 is complete when:

- there is one shell, not separate page systems
- home/results state changes happen in one component tree
- the code clearly reflects the product model

## Validation

Required checks:

- `cd frontend-v2 && npm run build`
- `cd frontend-v2 && npm run lint`

## Commit Plan

Docs commit:

- `docs: phase 1 implementation plan`

Implementation commit:

- `feat: add frontend v2 search shell`
