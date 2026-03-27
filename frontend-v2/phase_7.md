# Phase 7 Implementation Plan

## Goal

Finish v2 by simplifying anything that still feels heavier than it should, then polish only the parts that sharpen the core flow.

## Scope

Included:

- simplification audit
- dead code removal
- small layout and copy cleanup
- only essential styling refinements

Excluded:

- new features
- new frameworks
- new state systems
- decorative background systems
- SEO work unless something is clearly broken
- decorative JS choreography that is not essential

## Implementation Shape

Focus areas:

- trim anything that grew during phases 1 through 6
- simplify state or component boundaries if they already feel strained
- tighten visual hierarchy only where it clarifies the existing flow
- make the home-to-results and results-to-overlay flow feel intentional without adding new mechanisms

## Acceptance Criteria

Phase 7 is complete when:

- the app feels finished
- no unnecessary abstractions remain
- the visual language is coherent
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
