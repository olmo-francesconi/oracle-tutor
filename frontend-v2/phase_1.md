# Phase 1 Implementation Plan

## Goal

Establish the minimal application shell and top-level state model.

## Scope

Included:

- create a single `SearchShell`
- keep home and results as two states of one app
- define top-level state in one place
- create a simple visual transition between home and results
- use placeholder content only to prove the shell architecture

Excluded:

- real API calls
- any real search box implementation
- editable input logic
- suggestions
- filter UI
- full search box logic
- overlay logic
- card detail plumbing

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

State can be stubbed with empty values where necessary.

## UI Plan

Render:

- a home hero state when `submittedQuery` is null
- a results state when `submittedQuery` exists
- one shared top-level shell

The first version can use placeholder content.

Phase 1 should prove:

- one state owner
- one component tree
- one shell that can move between home and results

Phase 1 should not try to feel like a real search product yet.

## Acceptance Criteria

Phase 1 is complete when:

- there is one shell, not separate page systems
- home/results state changes happen in one component tree
- the code clearly reflects the product model
- there is still no real search-box complexity in the app

## Validation

Required checks:

- `cd frontend-v2 && npm run build`
- `cd frontend-v2 && npm run lint`

## Commit Plan

Docs commit:

- `docs: phase 1 implementation plan`

Implementation commit:

- `feat: add frontend v2 search shell`
