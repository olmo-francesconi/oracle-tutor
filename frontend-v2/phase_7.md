# Phase 7 Implementation Plan

## Goal

Apply final polish without reintroducing architectural bloat.

## Scope

Included:

- final brutalist styling pass
- passive background treatments
- minimal SEO handling if still needed
- dead code removal
- simplicity audit

Excluded:

- new frameworks
- new state systems
- decorative JS choreography that is not essential

## Implementation Shape

Focus areas:

- tighten visual hierarchy
- make the home-to-results transition feel deliberate
- ensure all passive visual layers stay passive
- trim anything that grew during phases 1 through 6

## Acceptance Criteria

Phase 7 is complete when:

- the app feels finished
- no unnecessary abstractions remain
- the visual language is strong
- the code still reads like a small app

## Validation

Required checks:

- `cd frontend-v2 && npm run build`
- `cd frontend-v2 && npm run lint`

Manual checks:

- review home state
- review results state
- review overlay state
- re-read the code for complexity drift

## Commit Plan

Docs commit:

- `docs: phase 7 implementation plan`

Implementation commit:

- `refactor: finalize frontend v2 simplicity pass`
