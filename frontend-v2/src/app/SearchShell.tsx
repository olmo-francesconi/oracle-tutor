import { useCallback, useEffect, useRef, useState } from 'react'
import { FilterBar } from '../components/FilterBar'
import { ResultsGrid } from '../components/ResultsGrid'
import { SearchBox } from '../components/SearchBox/SearchBox'
import { DenseTextBackground } from '../components/background/DenseTextBackground'
import { HomeEditorialText } from '../components/background/HomeEditorialText'
import {
  buildCardLoadingState,
  buildCardSuccessState,
  buildClearedState,
  buildSearchFailureState,
  getApiDownMessage,
  buildSearchLoadingState,
  buildSearchSuccessState,
  isApiDownError,
  getSearchErrorMessage,
} from './searchShellState'
import { getActiveFilterCount, normalizeFilterState } from '../lib/filters'
import { getCard, getOracleSamples, getSimilarCards, searchOracleText } from '../lib/api'
import { reportError, track } from '../lib/observability'
import { readSearchStateFromUrl, writeSearchStateToUrl } from '../lib/urlState'
import type { CardMatch, FilterState, OracleSamples } from '../types/api'
import type { PinnedCard, SearchShellState } from '../types/ui'
import { ApiDownOverlay } from '../components/errors/ApiDownOverlay'
import { SearchErrorPanel } from '../components/errors/SearchErrorPanel'

const RESULTS_PAGE_SIZE = 24
const LEFT_STRIPE_WIDTH_PX = 6

type ViewportSize = {
  width: number
  height: number
}

const INITIAL_STATE: SearchShellState = {
  draftQuery: '',
  submittedQuery: null,
  pinnedCard: null,
  filters: {},
  error: null,
  results: [],
  hasMore: false,
  isLoading: false,
  isLoadingMore: false,
}

const EMPTY_ORACLE_SAMPLES: OracleSamples = {
  texts: [],
  terms: [],
}

const DEFAULT_VIEWPORT: ViewportSize = {
  width: 1280,
  height: 900,
}

function getViewportSize(): ViewportSize {
  if (typeof window === 'undefined') {
    return DEFAULT_VIEWPORT
  }

  return {
    width: Math.max(window.innerWidth, 0),
    height: Math.max(window.innerHeight, window.screen?.height ?? 0),
  }
}

function getInitialState(): SearchShellState {
  const initialUrlState = readSearchStateFromUrl()

  if (initialUrlState.pinnedCard) {
    return {
      ...INITIAL_STATE,
      pinnedCard: { ...initialUrlState.pinnedCard, name: '' },
      filters: initialUrlState.filters,
      isLoading: true,
    }
  }

  const initialQuery = initialUrlState.query
  if (!initialQuery) {
    return INITIAL_STATE
  }

  return {
    ...INITIAL_STATE,
    draftQuery: initialQuery,
    submittedQuery: initialQuery,
    filters: initialUrlState.filters,
    isLoading: true,
  }
}

export function SearchShell() {
  const [state, setState] = useState<SearchShellState>(getInitialState)
  const [oracleSamples, setOracleSamples] = useState<OracleSamples>(EMPTY_ORACLE_SAMPLES)
  const [apiDownMessage, setApiDownMessage] = useState<string | null>(null)
  const [isRetryingApi, setIsRetryingApi] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [viewport, setViewport] = useState<ViewportSize>(getViewportSize)
  const activeSearchRequestRef = useRef<AbortController | null>(null)
  const activeLoadMoreRequestRef = useRef<AbortController | null>(null)
  const hasLoadedInitialQueryRef = useRef(false)
  const skipNextUrlWriteRef = useRef(state.submittedQuery !== null)
  const resizeFrameRef = useRef<number | null>(null)

  const isHome = state.submittedQuery === null
  const activeFilterCount = getActiveFilterCount(state.filters)
  const hasOracleBackground = oracleSamples.texts.length > 0
  const handleDraftChange = useCallback((value: string) => {
    setState((current) => ({
      ...current,
      draftQuery: value,
    }))
  }, [])

  const fetchFirstPage = useCallback(async (query: string, filters: SearchShellState['filters'], signal: AbortSignal) => {
    return searchOracleText(query, 0, RESULTS_PAGE_SIZE, filters, signal)
  }, [])

  const runCardSearch = useCallback(async (oracleId: string, faceIx: number, name: string, filters: FilterState) => {
    activeSearchRequestRef.current?.abort()
    activeLoadMoreRequestRef.current?.abort()

    const controller = new AbortController()
    activeSearchRequestRef.current = controller

    setState((current) => buildCardLoadingState(current, { oracle_id: oracleId, face_ix: faceIx, name }, filters))

    try {
      const [cardData, page] = await Promise.all([
        name ? Promise.resolve({ name }) : getCard(oracleId, controller.signal),
        getSimilarCards(oracleId, faceIx, 0, RESULTS_PAGE_SIZE, filters, controller.signal),
      ])

      if (controller.signal.aborted) return

      const pinnedCard: PinnedCard = { oracle_id: oracleId, face_ix: faceIx, name: cardData.name }
      setApiDownMessage(null)
      setState((current) => buildCardSuccessState(current, pinnedCard, filters, page))
    } catch (error) {
      if (controller.signal.aborted) return

      reportError(error, { source: 'card.similar', oracleId })
      if (isApiDownError(error)) {
        setApiDownMessage(getApiDownMessage(error))
        setState((current) => ({ ...current, isLoading: false, isLoadingMore: false }))
        return
      }

      setApiDownMessage(null)
      setState((current) => ({
        ...current,
        error: getSearchErrorMessage(error),
        isLoading: false,
        isLoadingMore: false,
      }))
    }
  }, [])

  const loadOracleSamples = useCallback(async (signal?: AbortSignal) => {
    const nextSamples = await getOracleSamples(signal)
    if (signal?.aborted) return false

    setOracleSamples(nextSamples)
    setApiDownMessage(null)
    return true
  }, [])

  const runSearch = useCallback(async (query: string, filters: FilterState) => {
    activeSearchRequestRef.current?.abort()
    activeLoadMoreRequestRef.current?.abort()

    const controller = new AbortController()
    activeSearchRequestRef.current = controller

    setState((current) => buildSearchLoadingState(current, query, filters))

    try {
      const page = await fetchFirstPage(query, filters, controller.signal)

      if (controller.signal.aborted) return

      setApiDownMessage(null)
      setState((current) => buildSearchSuccessState(current, query, filters, page))
    } catch (error) {
      if (controller.signal.aborted) return

      reportError(error, {
        source: 'search.first-page',
        query,
        filters,
      })
      if (isApiDownError(error)) {
        setApiDownMessage(getApiDownMessage(error))
        setState((current) => ({
          ...current,
          submittedQuery: query,
          filters,
          error: null,
          results: [],
          hasMore: false,
          isLoading: false,
          isLoadingMore: false,
        }))
        return
      }

      setApiDownMessage(null)
      setState((current) => buildSearchFailureState(current, query, filters, getSearchErrorMessage(error)))
    }
  }, [fetchFirstPage])

  const handleSubmit = useCallback((submittedValue?: string) => {
    const nextQuery = (submittedValue ?? state.draftQuery).trim()
    if (!nextQuery) return

    track('search_submitted', {
      queryLength: nextQuery.length,
      hasFilters: Object.keys(state.filters).length > 0,
    })

    setState((current) => ({
      ...current,
      draftQuery: nextQuery,
    }))

    void runSearch(nextQuery, state.filters)
  }, [runSearch, state.draftQuery, state.filters])

  const handleCardSelect = useCallback((card: CardMatch) => {
    if (!card.oracle_id) return
    track('card_selected', { oracleId: card.oracle_id, name: card.name })
    void runCardSearch(card.oracle_id, card.face_ix, card.name, state.filters)
  }, [runCardSearch, state.filters])

  const handleFiltersChange = useCallback((nextFilters: FilterState) => {
    const normalizedFilters = normalizeFilterState(nextFilters)
    const nextFilterKeys = Object.keys(normalizedFilters).sort()
    const previousFilterKeys = Object.keys(state.filters).sort()

    setState((current) => ({
      ...current,
      filters: normalizedFilters,
      error: null,
    }))

    track('filters_changed', {
      activeCount: nextFilterKeys.length,
      keys: nextFilterKeys,
      previousKeys: previousFilterKeys,
    })

    if (!state.submittedQuery) return
    if (state.pinnedCard) {
      void runCardSearch(state.pinnedCard.oracle_id, state.pinnedCard.face_ix, state.pinnedCard.name, normalizedFilters)
      return
    }
    void runSearch(state.submittedQuery, normalizedFilters)
  }, [runSearch, runCardSearch, state.filters, state.pinnedCard, state.submittedQuery])

  const handleClearFilters = useCallback(() => {
    const previousKeys = Object.keys(state.filters).sort()

    track('filters_cleared', {
      previousKeys,
    })

    setState((current) => ({
      ...current,
      filters: {},
      error: null,
    }))

    if (!state.submittedQuery) return
    if (state.pinnedCard) {
      void runCardSearch(state.pinnedCard.oracle_id, state.pinnedCard.face_ix, state.pinnedCard.name, {})
      return
    }
    void runSearch(state.submittedQuery, {})
  }, [runSearch, runCardSearch, state.filters, state.pinnedCard, state.submittedQuery])

  const handleLoadMore = useCallback(async () => {
    if (!state.submittedQuery || state.isLoading || state.isLoadingMore || !state.hasMore) {
      return
    }

    track('load_more_requested', {
      queryLength: state.submittedQuery.length,
      offset: state.results.length,
      hasFilters: Object.keys(state.filters).length > 0,
    })

    activeLoadMoreRequestRef.current?.abort()
    const controller = new AbortController()
    activeLoadMoreRequestRef.current = controller

    setState((current) => ({
      ...current,
      error: null,
      isLoadingMore: true,
    }))

    try {
      const page = state.pinnedCard
        ? await getSimilarCards(
            state.pinnedCard.oracle_id,
            state.pinnedCard.face_ix,
            state.results.length,
            RESULTS_PAGE_SIZE,
            state.filters,
            controller.signal
          )
        : await searchOracleText(
            state.submittedQuery!,
            state.results.length,
            RESULTS_PAGE_SIZE,
            state.filters,
            controller.signal
          )

      if (controller.signal.aborted) return

      setApiDownMessage(null)
      setState((current) => ({
        ...current,
        error: null,
        results: [...current.results, ...page.items],
        hasMore: page.has_more,
        isLoadingMore: false,
      }))
    } catch (error) {
      if (controller.signal.aborted) return

      reportError(error, {
        source: 'search.load-more',
        query: state.submittedQuery,
        offset: state.results.length,
        filters: state.filters,
      })
      if (isApiDownError(error)) {
        setApiDownMessage(getApiDownMessage(error))
        setState((current) => ({
          ...current,
          error: null,
          isLoadingMore: false,
        }))
        return
      }

      setApiDownMessage(null)
      setState((current) => ({
        ...current,
        error: getSearchErrorMessage(error),
        isLoadingMore: false,
      }))
    }
  }, [
    state.filters,
    state.hasMore,
    state.isLoading,
    state.isLoadingMore,
    state.pinnedCard,
    state.results.length,
    state.submittedQuery,
  ])

  const handleReset = useCallback(() => {
    activeSearchRequestRef.current?.abort()
    activeLoadMoreRequestRef.current?.abort()
    writeSearchStateToUrl(null, {})
    setState((current) => buildClearedState(current))
  }, [])

  const handleRetryApi = useCallback(async () => {
    setIsRetryingApi(true)

    try {
      if (state.submittedQuery) {
        await runSearch(state.submittedQuery, state.filters)
        return
      }

      await loadOracleSamples()
    } finally {
      setIsRetryingApi(false)
    }
  }, [loadOracleSamples, runSearch, state.filters, state.submittedQuery])

  useEffect(() => {
    const controller = new AbortController()

    void (async () => {
      try {
        await loadOracleSamples(controller.signal)
      } catch (error) {
        if (controller.signal.aborted) return

        reportError(error, {
          source: 'home.oracle-samples',
        })

        if (isApiDownError(error)) {
          setApiDownMessage(getApiDownMessage(error))
        } else {
          setApiDownMessage(null)
          setOracleSamples(EMPTY_ORACLE_SAMPLES)
        }
      }
    })()

    return () => controller.abort()
  }, [loadOracleSamples])

  useEffect(() => {
    const updateViewport = () => {
      setViewport(getViewportSize())
    }

    const scheduleUpdate = () => {
      if (resizeFrameRef.current !== null) return

      resizeFrameRef.current = window.requestAnimationFrame(() => {
        resizeFrameRef.current = null
        updateViewport()
      })
    }

    updateViewport()
    window.addEventListener('resize', scheduleUpdate)

    return () => {
      window.removeEventListener('resize', scheduleUpdate)

      if (resizeFrameRef.current !== null) {
        window.cancelAnimationFrame(resizeFrameRef.current)
      }
    }
  }, [])

  useEffect(() => {
    if (hasLoadedInitialQueryRef.current) return
    hasLoadedInitialQueryRef.current = true

    if (state.pinnedCard) {
      void runCardSearch(state.pinnedCard.oracle_id, state.pinnedCard.face_ix, '', state.filters)
      return
    }

    if (!state.submittedQuery) return
    void runSearch(state.submittedQuery, state.filters)
  }, [runSearch, runCardSearch, state.filters, state.pinnedCard, state.submittedQuery])

  useEffect(() => {
    const handlePopState = () => {
      const nextState = readSearchStateFromUrl()

      if (nextState.pinnedCard) {
        skipNextUrlWriteRef.current = true
        void runCardSearch(nextState.pinnedCard.oracle_id, nextState.pinnedCard.face_ix, '', nextState.filters)
        return
      }

      const nextQuery = nextState.query

      if (!nextQuery) {
        activeSearchRequestRef.current?.abort()
        activeLoadMoreRequestRef.current?.abort()
        skipNextUrlWriteRef.current = true
        setState((current) => buildClearedState(current))
        return
      }

      skipNextUrlWriteRef.current = true
      setState((current) => ({
        ...current,
        draftQuery: nextQuery,
        filters: nextState.filters,
        error: null,
      }))

      void runSearch(nextQuery, nextState.filters)
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [runSearch])

  useEffect(() => {
    if (skipNextUrlWriteRef.current) {
      skipNextUrlWriteRef.current = false
      return
    }

    if (state.submittedQuery === null && !state.pinnedCard) return
    writeSearchStateToUrl(state.submittedQuery, state.filters, state.pinnedCard)
  }, [state.filters, state.submittedQuery, state.pinnedCard?.oracle_id, state.pinnedCard?.face_ix])

  return (
    <main
      className={[
        'relative isolate min-h-screen bg-ot-bg',
        isHome ? 'grid place-items-center px-6 pb-16 pl-11 pt-12 max-[720px]:px-4 max-[720px]:pb-12 max-[720px]:pl-[30px] max-[720px]:pt-8' : '',
      ].join(' ')}
    >
      <DenseTextBackground
        texts={oracleSamples.texts}
        viewport={viewport}
        isVisible={hasOracleBackground}
        leftInset={LEFT_STRIPE_WIDTH_PX}
      />
      <div className="relative z-10">
        {isHome ? (
          <HomeEditorialText
            texts={oracleSamples.texts}
            terms={oracleSamples.terms}
            viewport={viewport}
            isVisible={hasOracleBackground}
            leftInset={LEFT_STRIPE_WIDTH_PX}
          />
        ) : null}

        <div className="fixed inset-y-0 left-0 z-20 w-1.5 bg-ot-red" aria-hidden="true" />

        {isHome ? (
          <section className="relative z-20 grid w-full max-w-[560px] gap-7" aria-label="Home state">
            <div className="grid gap-3 px-[18px] text-left max-[720px]:px-[14px]">
              <h1 className="m-0 font-display text-[clamp(4.5rem,11vw,7rem)] font-black uppercase leading-[0.86] tracking-[-0.03em]">
                <span className="block">Oracle</span>
                <span className="block">Tutor</span>
              </h1>
              <div className="h-0.5 w-full max-w-[18.5rem] bg-ot-ink" />
              <p className="m-0 max-w-[30ch] text-[0.8125rem] lowercase leading-[1.55] tracking-[0.06em] text-ot-muted">
                find cards by meaning, not keywords.
              </p>
            </div>

            <div className="grid gap-0">
              <SearchBox
                value={state.draftQuery}
                onChange={handleDraftChange}
                onSubmit={handleSubmit}
                onCardSelect={handleCardSelect}
                autoFocus
                showManaRail
                variant="home"
              />
            </div>
          </section>
        ) : (
          <>
            <div className="sticky top-0 z-30 max-[720px]:static">
            <header className="grid min-h-[58px] grid-cols-[clamp(148px,16vw,176px)_minmax(0,1fr)_auto] items-stretch border-b-2 border-ot-ink bg-ot-bg max-[720px]:grid-cols-[auto_minmax(0,1fr)_auto]">
              <button
                type="button"
                className="flex min-w-0 cursor-pointer items-center justify-center border-0 border-r-2 border-ot-ink bg-transparent px-[18px] py-0 font-display text-[20px] font-black uppercase leading-none tracking-[-0.02em] text-ot-ink transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] hover:bg-ot-ink hover:text-ot-bg motion-reduce:transition-none max-[720px]:min-h-14 max-[720px]:w-14 max-[720px]:min-w-14 max-[720px]:px-0 max-[720px]:text-[18px]"
                onClick={handleReset}
              >
                <span className="max-[720px]:hidden">Oracle Tutor</span>
                <span className="hidden max-[720px]:inline">OT</span>
              </button>
              <div className="relative flex min-w-0 items-stretch bg-ot-surface">
                <SearchBox
                  className="h-full self-stretch"
                  value={state.draftQuery}
                  onChange={handleDraftChange}
                  onSubmit={handleSubmit}
                  onCardSelect={handleCardSelect}
                  autoFocus={false}
                  showManaRail={false}
                  variant="topbar"
                />
              </div>
              <button
                type="button"
                onClick={() => setShowFilters((v) => !v)}
                className={[
                  'flex shrink-0 cursor-pointer items-center justify-center gap-2 border-l-2 border-ot-ink px-4 font-display text-[0.6875rem] font-black uppercase tracking-[0.12em] transition-colors duration-150 ease-[cubic-bezier(0.25,1,0.5,1)] motion-reduce:transition-none max-[720px]:w-14 max-[720px]:min-w-14 max-[720px]:px-0',
                  showFilters || activeFilterCount > 0
                    ? 'bg-ot-ink text-ot-bg'
                    : 'bg-transparent text-ot-ink hover:bg-ot-ink hover:text-ot-bg',
                ].join(' ')}
                aria-expanded={showFilters}
                aria-label="Toggle filters"
              >
                <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 shrink-0" fill="currentColor" aria-hidden="true">
                  <path d="M1 3h14l-5 5.5V13l-4 1.5V8.5L1 3Z" />
                </svg>
                <span className="max-[720px]:hidden">Filters</span>
                {activeFilterCount > 0 && (
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center bg-ot-red font-display text-[0.5625rem] font-black text-white max-[720px]:hidden">
                    {activeFilterCount}
                  </span>
                )}
              </button>
            </header>

            <section
              className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-x-8 gap-y-[18px] border-b-2 border-ot-ink bg-ot-bg px-6 pb-[18px] pl-[38px] pr-6 pt-4 max-[720px]:grid-cols-1 max-[720px]:gap-[10px] max-[720px]:px-4 max-[720px]:pb-4 max-[720px]:pl-6 max-[720px]:pt-[14px]"
              aria-label="Results summary"
            >
              <div className="grid max-w-[min(34rem,100%)] gap-1 max-[720px]:gap-0.5">
                <p className="eyebrow">{state.pinnedCard ? 'Similar to' : 'Results'}</p>
                <h2 className="m-0 font-display text-[clamp(2.2rem,4.4vw,3.35rem)] font-black uppercase leading-[0.9] tracking-[-0.02em]">
                  {state.submittedQuery}
                </h2>
              </div>
              <div className="grid min-w-[13rem] justify-items-end gap-1.5 self-center max-[720px]:min-w-0 max-[720px]:justify-items-start">
                {!state.isLoading ? (
                  <span className="m-0 text-xs uppercase tracking-[0.11em] text-ot-muted" aria-live="polite">
                    {state.results.length}
                    {state.hasMore || state.isLoadingMore ? '+' : ''} cards
                  </span>
                ) : null}
              </div>
            </section>

            {showFilters && (
              <FilterBar filters={state.filters} onChange={handleFiltersChange} onClear={handleClearFilters} />
            )}
            </div>

            <section
              className="px-6 pb-14 pl-[38px] pr-6 pt-6 max-[720px]:px-4 max-[720px]:pl-6"
              aria-label="Results state"
            >
              {state.isLoading ? (
                <div className="grid gap-3" aria-hidden="true">
                  <div className="grid gap-1.5">
                    <span className="block h-3 w-28 animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_82%,var(--color-ot-bg))]" />
                    <span className="block h-8 w-[min(24rem,78vw)] animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_82%,var(--color-ot-bg))]" />
                  </div>
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(164px,1fr))] gap-3 max-[720px]:grid-cols-[repeat(auto-fill,minmax(154px,1fr))]">
                    {Array.from({ length: 6 }, (_, index) => (
                      <div key={index} className="grid gap-0 border-2 border-ot-ink bg-ot-surface">
                        <span className="block h-8 animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_82%,var(--color-ot-bg))]" />
                        <span className="block aspect-[63/88] animate-ot-loading-pulse bg-[color:color-mix(in_srgb,var(--color-ot-line)_72%,var(--color-ot-bg))]" />
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              {!state.isLoading && state.error ? <SearchErrorPanel message={state.error} /> : null}
              {!state.isLoading && !state.error && state.results.length === 0 ? (
                <p className="m-0 text-xs uppercase tracking-[0.11em] text-ot-muted">
                  No cards matched {state.submittedQuery ? `"${state.submittedQuery}"` : 'this search'}.
                </p>
              ) : null}
              {state.results.length > 0 ? (
                <ResultsGrid
                  cards={state.results}
                  hasMore={state.hasMore}
                  isLoadingMore={state.isLoadingMore}
                  onLoadMore={handleLoadMore}
                />
              ) : null}
            </section>
          </>
        )}
      </div>
      {apiDownMessage ? (
        <ApiDownOverlay
          message={apiDownMessage}
          isRetrying={isRetryingApi}
          onRetry={handleRetryApi}
        />
      ) : null}
    </main>
  )
}
