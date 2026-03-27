# Phase 0 Implementation Plan

## Goal

Create a clean `frontend-v2` app with the smallest viable setup for the rebuild.

## Scope

This phase only covers setup and baseline tooling.

Included:

- create the Vite React TypeScript app structure
- install the minimal dependency set
- add base styling and token setup
- add `mana-font`
- make sure build and lint run

Explicitly excluded:

- app state
- search shell
- API integration
- results rendering
- card overlay

## Dependencies

Expected runtime dependencies:

- `react`
- `react-dom`
- `mana-font`
- `clsx` only if we immediately need it

Expected dev dependencies:

- Vite defaults for React + TypeScript
- ESLint

Do not install:

- `react-router-dom`
- `axios`
- `@tanstack/react-query`
- `framer-motion`
- `react-helmet-async`

## File Plan

Create:

- `frontend-v2/package.json`
- `frontend-v2/tsconfig*.json`
- `frontend-v2/vite.config.ts`
- `frontend-v2/index.html`
- `frontend-v2/src/main.tsx`
- `frontend-v2/src/App.tsx`
- `frontend-v2/src/styles.css`

Optional at this phase:

- `frontend-v2/src/lib/`
- `frontend-v2/src/components/`

Only if needed to keep imports tidy.

## Styling Plan

Add a very small token layer in `styles.css`:

- background
- surface
- ink
- red accent
- muted tone

Add the font rules:

- display font for headings
- DM Mono for body/UI if loaded from Google Fonts
- `mana-font` integration

Do not add:

- full component styling
- complex animations
- page-specific layouts

## Acceptance Criteria

Phase 0 is complete when:

- `frontend-v2` exists as a standalone app
- `npm run build` passes
- `npm run lint` passes
- the app renders a minimal placeholder screen
- `mana-font` is available in CSS
- dependency list matches the minimal stack

## Validation

Required checks:

- `cd frontend-v2 && npm run build`
- `cd frontend-v2 && npm run lint`

Optional sanity check:

- run dev server and confirm the placeholder app renders

## Commit Plan

Docs commit:

- `docs: phase 0 implementation plan`

Implementation commit:

- `feat: bootstrap frontend v2 app`
