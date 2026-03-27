# Frontend V2 Plan

## Purpose

Build a simpler replacement for the current frontend.

The core rule for v2:

- The website is small.
- The search box is the only intentionally complex part.
- Everything else should be simple, boring, and easy to understand.

This document is the source of truth for v2 scope and progress.

## Product Goals

1. Keep the app extremely small and understandable.
2. Preserve the key Oracle Tutor UX:
   - search by meaning
   - strong typeahead and semantic suggestion behavior
   - mana symbol entry
   - fast card browsing
3. Keep the brutalist editorial visual language.
4. Avoid carrying over architecture that only exists to support polish we do not need.

## Non-Goals

Do not add these unless we prove they are necessary:

- animation libraries
- React Query
- axios
- head management libraries
- a large design system
- multiple page-specific state systems
- JS-heavy layout choreography outside the search box

## Tech Stack

Initial stack:

- Vite
- React
- TypeScript
- native `fetch`

Allowed utility dependency:

- `clsx` if needed

Everything else starts as "no" by default.

Routing decision for v2 start:

- do not use React Router initially
- begin as a single-page app with internal state transitions
- revisit routing only after the core app is working cleanly

## Target Architecture

V2 should be organized around one search shell, not around separate page systems.

### App Model

- One app shell
- Two primary visual states:
  - home
  - results
- Optional card detail overlay state

### Top-Level State

The main state should live in one place:

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
- `selectedCardId`

### Core Components

- `App`
- `SearchShell`
- `SearchBox`
- `ResultsGrid`
- `CardOverlay`
- `HomeHero`

### Supporting Modules

- `api.ts`
- `cards.ts`
- `manaSymbols.ts`
- `urlState.ts`
- `seo.ts` only if still needed after MVP

## Proposed Folder Structure

```text
frontend-v2/
  src/
    main.tsx
    App.tsx
    styles.css

    app/
      SearchShell.tsx
      routes.ts

    components/
      SearchBox/
        SearchBox.tsx
        SearchInput.tsx
        SearchSuggestions.tsx
        ManaSymbolRail.tsx
      ResultsGrid.tsx
      CardOverlay.tsx
      HomeHero.tsx

    lib/
      api.ts
      cards.ts
      manaSymbols.ts
      urlState.ts
      seo.ts

    types/
      api.ts
      ui.ts
```

## Design Rules

Carry over the existing design direction, but not the current implementation complexity.

- brutalist editorial
- warm newsprint background
- strong typography
- minimal chrome
- no decorative framework complexity

Specific implementation constraints:

- prefer CSS over JS layout logic
- avoid runtime measurements unless required for search UX
- decorative layers must stay passive
- no route-specific visual systems if one shared shell works

## What To Reuse From Current Frontend

Likely reusable:

- API response shapes
- card and search-related types
- mana symbol parsing logic
- card image URL helpers
- visual tokens and typography choices
- proven search UX details

Must preserve in v2:

- `mana-font`
- automatic symbol insertion
- symbol-rich header treatment
- at least card name suggestions

Likely not reusable as-is:

- current page architecture
- current homepage orchestration
- current results page shell
- heavy local page state coordination
- most non-search measurements and choreography

## Delivery Phases

### Phase 0: Setup

Goal:
- create a clean Vite app with minimal dependencies

Tasks:
- create `frontend-v2`
- add React + TypeScript
- keep routing out initially
- add base stylesheet and token layer
- install `mana-font`

Definition of done:
- app boots locally
- build works
- dependency list stays intentionally small

### Phase 1: Minimal Shell

Goal:
- establish the simplest possible application structure

Tasks:
- create `App.tsx`
- create `SearchShell.tsx`
- define top-level app state
- support home state and results state in one shell
- design the move from search to results as one continuous SPA interaction

Definition of done:
- app can switch between home and results presentation without separate page systems

### Phase 2: API Layer

Goal:
- create the smallest useful data layer

Tasks:
- implement `fetch` helpers
- add:
  - `searchCards`
  - `searchOracleText`
  - `getCard`
  - `getSimilarCards`
  - `getOracleSamples`
- add error handling and query param helpers

Definition of done:
- all current backend endpoints used by the frontend are reachable through one small API module

### Phase 3: Search Box

Goal:
- rebuild the one component allowed to be sophisticated

Tasks:
- implement editable input
- support mana symbols
- support automatic symbol insertion
- support name suggestions
- support semantic suggestions if still justified after MVP
- support keyboard navigation
- support submit behavior
- support open/close behavior

Constraints:
- keep internal complexity inside the search box
- avoid parent-child control plumbing unless clearly necessary

Definition of done:
- the search box supports the intended UX without spreading complexity through the rest of the app
- card name suggestions work
- `mana-font` integration works cleanly

### Phase 4: Results

Goal:
- render search results simply

Tasks:
- implement `ResultsGrid`
- implement infinite scroll
- implement card tile rendering
- wire selection into overlay state

Definition of done:
- submitted searches render usable results with simple, understandable code

### Phase 5: Card Overlay

Goal:
- support focused card inspection without turning it into another app mode

Tasks:
- implement `CardOverlay`
- fetch fuller card data only if needed
- support close behavior
- add next/prev only if clearly worth the complexity
- include symbol-rich header treatment

Definition of done:
- card inspection works without creating a second architecture inside the app

### Phase 6: URL State

Goal:
- make the experience linkable without bloating the architecture

Tasks:
- add lightweight History API handling if needed
- sync submitted query to URL
- evaluate whether `/card/:id` can be added without introducing router complexity
- if `/card/:id` meaningfully complicates the app, defer it until after the SPA is clean

Definition of done:
- home and results states can be linked directly

### Phase 7: Polish

Goal:
- bring back only the polish that earns its code cost

Tasks:
- apply final brutalist styling
- add passive background treatments
- add minimal SEO handling if needed
- remove dead code and unused helpers

Definition of done:
- visual quality is high
- architecture remains simple

## Progress Checklist

### Phase 0

- [x] Create `frontend-v2`
- [x] Install minimal dependencies
- [x] Add base styles
- [x] Add `mana-font`
- [x] Confirm build and lint

### Phase 1

- [ ] Create `App`
- [ ] Create `SearchShell`
- [ ] Model top-level state
- [ ] Support home/results states in one shell
- [ ] Design a clean SPA transition from search to results

### Phase 2

- [ ] Add `fetch` API helper
- [ ] Implement search endpoints
- [ ] Implement card endpoints
- [ ] Add shared error handling

### Phase 3

- [ ] Build search input
- [ ] Add mana symbol support
- [ ] Add automatic symbol insertion
- [ ] Add suggestions UI
- [ ] Add keyboard navigation
- [ ] Add submit behavior
- [ ] Keep complexity internal

### Phase 4

- [ ] Build results grid
- [ ] Render result cards
- [ ] Add infinite scroll
- [ ] Wire selection state

### Phase 5

- [ ] Build card overlay
- [ ] Support card detail fetch
- [ ] Support close behavior
- [ ] Decide on next/prev navigation
- [ ] Add symbol-rich card header

### Phase 6

- [ ] Add lightweight URL syncing
- [ ] Re-evaluate `/card/:id`
- [ ] Confirm direct-link behavior

### Phase 7

- [ ] Add final visual polish
- [ ] Add only essential SEO handling
- [ ] Remove dead code
- [ ] Re-audit complexity before launch

## Guardrails

When building v2, stop and reconsider if any change introduces:

- a new global abstraction
- page-specific state machines
- decorative JS measurement
- a dependency that saves little code
- more than one place that owns search behavior

If that happens, the default answer should be to simplify, not to add structure.

## Current Decisions

1. Do not use React Router initially.
2. Keep `/card/:id` as a desired outcome, but not at the cost of making the early architecture heavier.
3. Use infinite scroll.
4. Must preserve:
   - `mana-font`
   - automatic symbol insertion
   - symbol-rich header treatment
   - at least card name suggestions
5. Keep the basic homepage ideas, but use the SPA model to make the move from search to results feel more unified.

## Remaining Open Decision

1. When should direct `/card/:id` support be introduced, and can it be done without dragging in router complexity too early?

## Definition Of Success

V2 is successful if:

- a new engineer can understand the structure quickly
- the search box is clearly the only complex subsystem
- the rest of the app feels small
- the code structure matches the product structure
- we do not recreate v1 with cleaner file names
