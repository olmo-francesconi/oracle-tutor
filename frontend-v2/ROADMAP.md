# frontend-v2 Production Readiness Roadmap

_Reviewed against the current implementation on 2026-03-27._

Target:
- Ship a stable search experience
- Close the biggest user-facing gaps first
- Keep scope aligned with the "small app, simple shell" plan

Status labels:
- `Missing`: not implemented
- `Partial`: partly implemented, but not release-ready
- `Done`: implemented in the current code

---

## Phase 1 — Launch blockers

These are the gaps most likely to make the app feel broken or unfinished.

### 1.1 Render real error states
Status: `Missing`

Current state:
- `assertOk` already returns descriptive errors in [src/lib/api.ts](./src/lib/api.ts)
- `SearchShellState` has no `error` field in [src/types/ui.ts](./src/types/ui.ts)
- `runSearch` and the initial query effect both swallow failures and only clear results in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)
- The results area renders loading and empty states, but no failure message in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)

Tasks:
- Add an `error` field to `SearchShellState`
- Populate it in `buildSearchFailureState`
- Render an inline failure state in the results area
- Distinguish offline/network failures from API validation failures
- Decide whether load-more failures get an inline retry affordance or only a non-blocking message

### 1.2 Build and wire the filter UI
Status: `Missing`

Current state:
- Filter types exist in [src/types/api.ts](./src/types/api.ts)
- `state.filters` exists in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)
- Filter params are already passed into `searchOracleText` and `getSimilarCards` through [src/lib/api.ts](./src/lib/api.ts)
- There is no filter control UI, no filter reset action, and no filter URL persistence anywhere in `src/`

Tasks:
- Build filter controls for color, CMC, card type, rarity, and format
- Wire controls to `state.filters`
- Add a clear-filters action
- Persist filters to URL state alongside the query
- Trigger a fresh page-0 fetch whenever filters change

### 1.3 Fix pagination and request coordination edge cases
Status: `Partial`

Current state:
- `ResultsGrid` avoids re-subscribing the observer on every render by using `onLoadMoreRef` in [src/components/ResultsGrid.tsx](./src/components/ResultsGrid.tsx)
- `handleLoadMore` guards against duplicate loads in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)
- The sentinel still renders while loading more, so the UI is guarded but not visibly disabled in [src/components/ResultsGrid.tsx](./src/components/ResultsGrid.tsx)
- Load-more requests use a separate `AbortController` that is never cancelled by later searches or filter changes in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)
- There is still no filter-change flow to reset pagination cleanly

Tasks:
- Cancel in-flight load-more requests when a new search starts
- Cancel in-flight load-more requests when filters change
- Make the loading-more state visibly disabled, not just internally guarded
- Add regression coverage for submit/search/load-more overlap

### 1.4 Fix the search input security risk
Status: `Partial`

Current state:
- `SearchInput` now checks `SAFE_MANA_TOKEN_RE` before creating icon nodes in [src/components/SearchBox/SearchInput.tsx](./src/components/SearchBox/SearchInput.tsx)
- That materially reduces the original XSS concern
- The regex is broader than the actual mana symbol allowlist, so unknown token shapes still fall through to text instead of icons only because `getManaClass` returns nothing

Tasks:
- Replace the regex-only gate with an explicit allowlist based on supported mana symbols
- Add tests for malicious, unknown, and valid token paths

---

## Phase 2 — Correctness and test coverage

The app's complexity is concentrated in a small number of files. Those files need tests before more behavior is added.

### 2.1 Add tests for the SearchShell state machine
Status: `Missing`

Current state:
- There are no frontend tests configured in [package.json](./package.json)
- No app tests exist under `frontend-v2/src/`
- `SearchShell` owns query submission, initial URL hydration, pagination, overlay selection, and URL writes in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)

Tasks:
- Add a frontend test runner
- Unit test `buildSearchLoadingState`, `buildSearchSuccessState`, `buildSearchFailureState`, and `buildClearedState`
- Add integration tests for submit, initial URL load, success, empty results, and load-more
- Add tests for back/forward navigation behavior

### 2.2 Add tests for the API layer
Status: `Missing`

Current state:
- `api.ts` contains normalization, error handling, cache logic, and filter param serialization in [src/lib/api.ts](./src/lib/api.ts)
- None of that logic is covered today

Tasks:
- Unit test `assertOk` across JSON and non-JSON failure responses
- Unit test `searchCards` cache hit/miss/eviction behavior
- Unit test `buildSimilarCardsParams` with partial and full filter objects
- Test normalization of card, match, and similar-card payloads

### 2.3 Add coverage for URL state
Status: `Partial`

Current state:
- Query read/write helpers exist in [src/lib/urlState.ts](./src/lib/urlState.ts)
- Query persistence works for `q`
- Filters are not represented in URL state
- There is no validation or test coverage for back/forward or malformed params

Tasks:
- Test initial query hydration
- Test `pushState` behavior on submit and reset
- Extend URL state to include filters once the filter UI exists
- Add validation for malformed or partial URL params if needed

---

## Phase 3 — UX, accessibility, and responsive behavior

This phase is mostly refinement, but a few items should happen before launch if time allows.

### 3.1 Strengthen loading, empty, and no-match UX
Status: `Partial`

Current state:
- Results loading text exists in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)
- Zero-results text already exists in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)
- Suggestion loading and no-match states already exist in [src/components/SearchBox/SearchSuggestions.tsx](./src/components/SearchBox/SearchSuggestions.tsx)
- There is no richer initial-load skeleton, and no separate visual treatment for initial load versus load more

Tasks:
- Decide whether text-only loading is sufficient or replace it with a lightweight skeleton
- Differentiate initial page load from incremental pagination visually
- Keep the empty state query-specific once error handling lands

### 3.2 Accessibility pass on suggestions, overlay, and announcements
Status: `Partial`

Current state:
- The app uses semantic buttons and a visible focus style in [src/styles.css](./src/styles.css)
- `SearchSuggestions` exposes `role="listbox"` but suggestion rows are still plain buttons without `role="option"` or `aria-selected` in [src/components/SearchBox/SearchSuggestions.tsx](./src/components/SearchBox/SearchSuggestions.tsx)
- `CardOverlay` does not trap focus or restore it on close in [src/components/CardOverlay.tsx](./src/components/CardOverlay.tsx)
- The results count is not announced through an `aria-live` region in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)
- The mana rail is keyboard reachable, but the mobile scroll buttons are small at `24x24` in [src/components/SearchBox/ManaSymbolRail.tsx](./src/components/SearchBox/ManaSymbolRail.tsx)

Tasks:
- Make suggestion items true listbox options
- Add `aria-live="polite"` to the results count or results summary
- Trap and restore focus for the detail rail if it remains an overlay-style interaction
- Increase small-screen control hit areas where needed

### 3.3 Verify mobile behavior
Status: `Partial`

Current state:
- The layout has mobile breakpoints in [src/app/SearchShell.tsx](./src/app/SearchShell.tsx)
- The overlay becomes static on narrow layouts in [src/components/CardOverlay.tsx](./src/components/CardOverlay.tsx)
- The mana rail has touch drag handling in [src/components/SearchBox/ManaSymbolRail.tsx](./src/components/SearchBox/ManaSymbolRail.tsx)
- The filter UI does not exist yet, so responsive behavior there is still unknown

Tasks:
- Verify the current layout on narrow screens once results and overlay are both present
- Confirm mana-rail drag behavior in real mobile browsers
- Design the filter UI mobile layout before implementation

---

## Phase 4 — Production hardening and ops

These items matter, but they should follow the core search and filter work.

### 4.1 Add an ErrorBoundary
Status: `Missing`

Current state:
- The app is mounted directly with no render-failure fallback in [src/main.tsx](./src/main.tsx)

Tasks:
- Wrap the app in an `ErrorBoundary`
- Render a recoverable fallback for uncaught render errors

### 4.2 Add runtime error reporting
Status: `Missing`

Current state:
- No Sentry or similar integration exists anywhere in `frontend-v2/`

Tasks:
- Add a small production error reporting integration after user-facing errors and the ErrorBoundary are in place
- Capture search failures, uncaught render failures, and overlay fetch failures

### 4.3 Add security headers in the production serving layer
Status: `Missing`

Current state:
- [Dockerfile](./Dockerfile) only starts the Vite dev server
- There is no nginx or production header config inside `frontend-v2/`

Tasks:
- Decide where production static assets are served
- Add CSP, `X-Frame-Options`, `X-Content-Type-Options`, and `Referrer-Policy` there

### 4.4 Add lightweight analytics
Status: `Missing`

Current state:
- No analytics hooks exist today

Tasks:
- Track search submits, filter usage, and card opens if product feedback is needed after launch
- Keep the implementation small and easy to remove

---

## Summary checklist

| Area | Item | Status | Priority |
|------|------|--------|----------|
| Phase 1 | Render error states in UI | Missing | Must have |
| Phase 1 | Build filter UI and URL sync | Missing | Must have |
| Phase 1 | Pagination/request coordination | Partial | Must have |
| Phase 1 | Search input token hardening | Partial | Must have |
| Phase 2 | SearchShell tests | Missing | Must have |
| Phase 2 | API layer tests | Missing | Must have |
| Phase 2 | URL state coverage | Partial | Should have |
| Phase 3 | Loading and empty-state polish | Partial | Should have |
| Phase 3 | Accessibility pass | Partial | Should have |
| Phase 3 | Mobile verification | Partial | Should have |
| Phase 4 | ErrorBoundary | Missing | Should have |
| Phase 4 | Error reporting | Missing | Nice to have |
| Phase 4 | Security headers | Missing | Should have |
| Phase 4 | Analytics | Missing | Nice to have |
