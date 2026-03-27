# frontend-v2 Code Review

_Reviewed: 2026-03-27_

---

## Critical

### 1. Potential XSS in SearchInput
**File:** `src/components/SearchBox/SearchInput.tsx:71`

`buildEditableContent` uses `replaceChildren()` to inject DOM nodes built from parsed mana tokens. If a crafted token like `{<img src=x onerror=alert(1)>}` passes the parser, it will be inserted into the DOM without sanitization.

**Proposed fix:** Validate each token against an allowlist of known mana symbols before building DOM nodes. Any token not matching the allowlist should be rendered as plain text.

```ts
const VALID_MANA_SYMBOL = /^\{[WUBRGCXYZSTPQ0-9/]+\}$/i;

function isSafeToken(token: string): boolean {
  return VALID_MANA_SYMBOL.test(token);
}
```

---

### 2. Memory leak in ResultsGrid IntersectionObserver
**File:** `src/components/ResultsGrid.tsx:91-102`

The `useEffect` that creates the IntersectionObserver lists `onLoadMore` in its dependency array. Because `onLoadMore` is a new function reference on every SearchShell render, the observer is torn down and recreated constantly. Old observers may fire before cleanup runs.

**Proposed fix:** Wrap `onLoadMore` in `useCallback` in SearchShell with a stable dependency set, and use a ref inside the effect to always call the latest version without re-subscribing.

```ts
// In ResultsGrid
const onLoadMoreRef = useRef(onLoadMore);
useEffect(() => { onLoadMoreRef.current = onLoadMore; });

useEffect(() => {
  const observer = new IntersectionObserver(([entry]) => {
    if (entry.isIntersecting && hasMore && !isLoadingMore) {
      onLoadMoreRef.current();
    }
  });
  if (sentinelRef.current) observer.observe(sentinelRef.current);
  return () => observer.disconnect();
}, [hasMore, isLoadingMore]); // onLoadMore no longer a dep
```

---

### 3. Stale closure race condition in SearchShell
**File:** `src/app/SearchShell.tsx:316`

The `fetchFirstPage` effect depends on `state.filters`, but reads `state.submittedQuery` via closure. When filters change after a query is submitted, the effect re-runs and may read a stale query value, triggering a fetch with mismatched parameters.

**Proposed fix:** Include all state values the effect reads in the dependency array, or restructure so filter changes and query submission are dispatched together and fetched in a single effect keyed to both.

```ts
useEffect(() => {
  if (!state.submittedQuery) return;
  fetchFirstPage(state.submittedQuery, state.filters);
}, [state.submittedQuery, state.filters, fetchFirstPage]);
```

---

## High

### 4. Silent API errors
**File:** `src/lib/api.ts:80-86`

`assertOk()` throws `"Request failed"` without including the response status or body. Server-side validation errors (400/422) are swallowed, leaving users staring at a spinner.

**Proposed fix:** Read and include the response body in the error message.

```ts
async function assertOk(res: Response): Promise<void> {
  if (res.ok) return;
  let detail = '';
  try {
    const body = await res.json();
    detail = body.detail ?? JSON.stringify(body);
  } catch {
    detail = await res.text().catch(() => '');
  }
  throw new Error(`Request failed: ${res.status}${detail ? ` — ${detail}` : ''}`);
}
```

---

### 5. Cache key collision
**File:** `src/lib/api.ts:169`

Cache keys are joined with `\u0000` as separator. If a user query happens to contain `\u0000`, keys from different queries can collide and return wrong cached results.

**Proposed fix:** Use a serialization that can't collide — `JSON.stringify` over an array is simple and safe.

```ts
const cacheKey = JSON.stringify([query, limit, offset, filters]);
```

---

### 6. Direct DOM mutation in ManaSymbolRail
**File:** `src/components/SearchBox/ManaSymbolRail.tsx:75-76`

`rail.dataset.dragging = 'true'` mutates a DOM node directly inside a React component to track drag state. This bypasses React's model and could cause subtle bugs as React reconciles the element.

**Proposed fix:** Use a `useRef` boolean to track drag state imperatively, or lift to component state if the value drives rendering.

```ts
const isDraggingRef = useRef(false);

// on drag start
isDraggingRef.current = true;

// on drag end
isDraggingRef.current = false;
```

---

## Medium

### 7. Repeated symbol key collision in SymbolText
**File:** `src/components/SymbolText.tsx:16,23`

Keys are generated as `${part}-${index}` where `index` resets per token group. Repeated symbols like `{W}{W}{W}` produce duplicate keys, causing React to reuse the wrong DOM nodes.

**Proposed fix:** Use a single incrementing index across all rendered parts.

```tsx
let keyIndex = 0;
parts.flatMap((part) => renderPart(part, keyIndex++));
```

---

### 8. Unbounded while loops in DenseTextBackground
**File:** `src/components/background/DenseTextBackground.tsx:26-41`

`buildRepeatedText` and `extendTextToLength` loop until a length threshold is reached with no iteration cap. If `texts` is empty or `MIN_TEXT_LENGTH` is unexpectedly large, the main thread freezes.

**Proposed fix:** Add a safety cap.

```ts
const MAX_ITERATIONS = 10_000;
let iterations = 0;
while (result.length < MIN_TEXT_LENGTH) {
  if (++iterations > MAX_ITERATIONS) break;
  result += texts[iterations % texts.length];
}
```

---

### 9. Incomplete unmount guard in CardOverlay fetch
**File:** `src/components/CardOverlay.tsx:46`

The `finally` block calls `setIsLoading(false)` regardless of whether the component has unmounted. The `!signal.aborted` guard is only checked in the `then` branch, not `finally`.

**Proposed fix:** Move the loading state update inside the abort check.

```ts
} catch (err) {
  if (!controller.signal.aborted) {
    setError(err instanceof Error ? err.message : 'Unknown error');
  }
} finally {
  if (!controller.signal.aborted) {
    setIsLoading(false);
  }
}
```

---

## Low

### 10. Dead `filters` state in SearchShell
**File:** `src/app/SearchShell.tsx`

`state.filters` is initialized but never passed to API calls. Either wire it into the search parameters or remove it to avoid confusion about what controls filtering.

---

### 11. No empty state in SearchSuggestions
**File:** `src/components/SearchBox/SearchSuggestions.tsx:20-40`

When `items.length === 0` and `isLoading` is false, the component returns `null` with no message. Users get no feedback that the query produced no suggestions.

**Proposed fix:** Render a subtle "No results" line instead of null.

---

### 12. Inconsistent className construction
**File:** Multiple (SearchBox.tsx, ResultsGrid.tsx, others)

Some files use `.filter(Boolean).join(' ')` while `clsx` is already available in the project. Standardize on `clsx` for all conditional class logic.

---

### 13. Missing URL validation in urlState
**File:** `src/lib/urlState.ts`

`window.history.pushState` is called with an unsanitized query string. Characters like `#` or malformed sequences could corrupt the URL.

**Proposed fix:** Use `URLSearchParams` to construct the query string safely.

```ts
const params = new URLSearchParams({ q: query });
const nextUrl = `${pathname}?${params.toString()}`;
window.history.pushState({ query }, '', nextUrl);
```

---

## Priority order

| # | Issue | Severity |
|---|-------|----------|
| 1 | SearchInput XSS via unsanitized mana tokens | Critical |
| 2 | IntersectionObserver memory leak | Critical |
| 3 | Stale closure race in SearchShell | Critical |
| 4 | API errors silently swallowed | High |
| 5 | Cache key collisions | High |
| 6 | DOM mutation bypassing React | High |
| 7 | SymbolText duplicate keys | Medium |
| 8 | Unbounded loops in background | Medium |
| 9 | Unmount guard in CardOverlay | Medium |
| 10 | Dead filters state | Low |
| 11 | Missing empty state in suggestions | Low |
| 12 | Inconsistent clsx usage | Low |
| 13 | URL not sanitized via URLSearchParams | Low |
