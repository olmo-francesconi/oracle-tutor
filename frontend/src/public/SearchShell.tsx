import { useCallback, useEffect, useRef, useState } from 'react'
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
import { writeSearchStateToUrl, readSearchStateFromUrl } from '../lib/urlState'
import type { CardMatch, FilterState, OracleSamples } from '../types/api'
import type { PinnedCard, SearchShellState } from '../types/ui'
import { ApiDownOverlay } from '../components/errors/ApiDownOverlay'
import { HomeView } from './HomeView'
import { ResultsView } from './ResultsView'
import { useUrlSync } from './useUrlSync'
import { useViewport } from './useViewport'

const RESULTS_PAGE_SIZE = 24

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
  const viewport = useViewport()
  const activeSearchRequestRef = useRef<AbortController | null>(null)
  const activeLoadMoreRequestRef = useRef<AbortController | null>(null)
  const hasLoadedInitialQueryRef = useRef(false)
  const skipNextUrlWriteRef = useRef(state.submittedQuery !== null)

  const isHome = state.submittedQuery === null
  const activeFilterCount = getActiveFilterCount(state.filters)
  const hasOracleBackground = oracleSamples.texts.length > 0

  const handleDraftChange = useCallback((value: string) => {
    setState((current) => ({ ...current, draftQuery: value }))
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
      const page = await searchOracleText(query, 0, RESULTS_PAGE_SIZE, filters, controller.signal)

      if (controller.signal.aborted) return

      setApiDownMessage(null)
      setState((current) => buildSearchSuccessState(current, query, filters, page))
    } catch (error) {
      if (controller.signal.aborted) return

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
  }, [])

  const handleSubmit = useCallback((submittedValue?: string) => {
    const nextQuery = (submittedValue ?? state.draftQuery).trim()
    if (!nextQuery) return

    setState((current) => ({ ...current, draftQuery: nextQuery }))
    void runSearch(nextQuery, state.filters)
  }, [runSearch, state.draftQuery, state.filters])

  const handleCardSelect = useCallback((card: CardMatch) => {
    if (!card.oracle_id) return
    void runCardSearch(card.oracle_id, card.face_ix, card.name, state.filters)
  }, [runCardSearch, state.filters])

  const handleFiltersChange = useCallback((nextFilters: FilterState) => {
    const normalizedFilters = normalizeFilterState(nextFilters)
    setState((current) => ({ ...current, filters: normalizedFilters, error: null }))

    if (!state.submittedQuery) return
    if (state.pinnedCard) {
      void runCardSearch(state.pinnedCard.oracle_id, state.pinnedCard.face_ix, state.pinnedCard.name, normalizedFilters)
      return
    }
    void runSearch(state.submittedQuery, normalizedFilters)
  }, [runSearch, runCardSearch, state.pinnedCard, state.submittedQuery])

  const handleClearFilters = useCallback(() => {
    setState((current) => ({ ...current, filters: {}, error: null }))

    if (!state.submittedQuery) return
    if (state.pinnedCard) {
      void runCardSearch(state.pinnedCard.oracle_id, state.pinnedCard.face_ix, state.pinnedCard.name, {})
      return
    }
    void runSearch(state.submittedQuery, {})
  }, [runSearch, runCardSearch, state.pinnedCard, state.submittedQuery])

  const handleLoadMore = useCallback(async () => {
    if (!state.submittedQuery || state.isLoading || state.isLoadingMore || !state.hasMore) {
      return
    }

    activeLoadMoreRequestRef.current?.abort()
    const controller = new AbortController()
    activeLoadMoreRequestRef.current = controller

    setState((current) => ({ ...current, error: null, isLoadingMore: true }))

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

      if (isApiDownError(error)) {
        setApiDownMessage(getApiDownMessage(error))
        setState((current) => ({ ...current, error: null, isLoadingMore: false }))
        return
      }

      setApiDownMessage(null)
      setState((current) => ({ ...current, error: getSearchErrorMessage(error), isLoadingMore: false }))
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
    if (hasLoadedInitialQueryRef.current) return
    hasLoadedInitialQueryRef.current = true

    if (state.pinnedCard) {
      void runCardSearch(state.pinnedCard.oracle_id, state.pinnedCard.face_ix, '', state.filters)
      return
    }

    if (!state.submittedQuery) return
    void runSearch(state.submittedQuery, state.filters)
  }, [runSearch, runCardSearch, state.filters, state.pinnedCard, state.submittedQuery])

  useUrlSync(
    state,
    skipNextUrlWriteRef,
    activeSearchRequestRef,
    activeLoadMoreRequestRef,
    setState,
    runSearch,
    runCardSearch,
  )

  return (
    <main
      className={[
        'relative isolate min-h-screen bg-ot-bg',
        isHome ? 'grid place-items-center px-6 pb-16 pl-11 pt-12 max-[720px]:px-4 max-[720px]:pb-12 max-[720px]:pl-[30px] max-[720px]:pt-8' : '',
      ].join(' ')}
    >
      {isHome ? (
        <HomeView
          draftQuery={state.draftQuery}
          oracleSamples={oracleSamples}
          viewport={viewport}
          hasOracleBackground={hasOracleBackground}
          onDraftChange={handleDraftChange}
          onSubmit={handleSubmit}
          onCardSelect={handleCardSelect}
        />
      ) : (
        <ResultsView
          state={state}
          showFilters={showFilters}
          activeFilterCount={activeFilterCount}
          onDraftChange={handleDraftChange}
          onSubmit={handleSubmit}
          onCardSelect={handleCardSelect}
          onReset={handleReset}
          onToggleFilters={() => setShowFilters((v) => !v)}
          onFiltersChange={handleFiltersChange}
          onClearFilters={handleClearFilters}
          onLoadMore={handleLoadMore}
        />
      )}
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
