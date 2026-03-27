# Phase 2 Implementation Plan

## Goal

Add the smallest useful API layer using native `fetch`.

## Scope

Included:

- request helper
- query param builder
- endpoint functions
- shared error handling

Excluded:

- caching abstraction
- retry abstraction
- global client wrapper complexity

## Implementation Shape

Main file:

- `src/lib/api.ts`

Functions:

- `searchCards`
- `searchOracleText`
- `getCard`
- `getSimilarCards`
- `getOracleSamples`

Support:

- `buildUrl`
- `assertOk`
- typed response parsing

## Constraints

- use native `fetch`
- keep the file small
- no custom client class
- no dependency on `axios`

## Acceptance Criteria

Phase 2 is complete when:

- all needed backend endpoints are reachable through one small module
- request code is readable and explicit
- abort signals can be passed where useful

## Validation

Required checks:

- `cd frontend-v2 && npm run build`
- `cd frontend-v2 && npm run lint`

If practical:

- add a temporary manual smoke call through the app

## Commit Plan

Docs commit:

- `docs: phase 2 implementation plan`

Implementation commit:

- `feat: add frontend v2 api layer`
