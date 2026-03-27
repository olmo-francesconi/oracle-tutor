# Phase 3 Implementation Plan

## Goal

Rebuild the search box as the only intentionally sophisticated subsystem.

## Scope

Included:

- `contenteditable` input
- inline rendered mana symbols instead of raw `{...}` tokens
- mana symbol insertion
- automatic symbol insertion behavior
- card name suggestions
- keyboard navigation
- submit behavior
- dropdown open/close behavior

Excluded unless clearly justified:

- every piece of semantic suggestion polish from v1
- complicated parent-controlled command plumbing

## Implementation Shape

Files:

- `src/components/SearchBox/SearchBox.tsx`
- `src/components/SearchBox/SearchInput.tsx`
- `src/components/SearchBox/SearchSuggestions.tsx`
- `src/components/SearchBox/ManaSymbolRail.tsx`

The search box should own its own interaction complexity.

Phase 3 should commit to the richer editor path now rather than starting with a plain input.

## Must Preserve

- `mana-font`
- automatic symbol insertion
- symbol-rich header treatment
- at least card name suggestions

## Design Constraints

- complexity stays internal to the search box
- parent components pass simple props
- avoid mode explosion
- prefer clear logic over clever editing abstractions
- do not re-import all of v1's search-box machinery; only bring over the pieces we still need

## Acceptance Criteria

Phase 3 is complete when:

- the search box is usable for real searches
- name suggestions work
- mana symbols render correctly
- inline symbol rendering works inside the editor itself
- the component remains understandable despite the UX richness

## Validation

Required checks:

- `cd frontend-v2 && npm run build`
- `cd frontend-v2 && npm run lint`

Manual checks:

- type card names and see suggestions
- insert mana symbols
- navigate suggestions by keyboard
- submit a search

## Commit Plan

Docs commit:

- `docs: phase 3 implementation plan`

Implementation commit:

- `feat: build frontend v2 search box`
