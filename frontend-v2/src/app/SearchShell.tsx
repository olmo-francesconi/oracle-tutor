import { useCallback, useEffect, useRef, useState } from 'react'
import { CardOverlay } from '../components/CardOverlay'
import { ResultsGrid } from '../components/ResultsGrid'
import { SearchBox } from '../components/SearchBox/SearchBox'
import { searchOracleText } from '../lib/api'
import { readSubmittedQueryFromUrl, writeSubmittedQueryToUrl } from '../lib/urlState'
import type { SimilarCard, SimilarCardsPage } from '../types/api'
import type { SearchShellState } from '../types/ui'

const RESULTS_PAGE_SIZE = 24

const INITIAL_STATE: SearchShellState = {
  draftQuery: '',
  submittedQuery: null,
  filters: {},
  results: [],
  hasMore: false,
  isLoading: false,
  isLoadingMore: false,
  selectedCard: null,
}

function buildSearchLoadingState(current: SearchShellState, query: string): SearchShellState {
  return {
    ...current,
    submittedQuery: query,
    results: [],
    hasMore: false,
    isLoading: true,
    isLoadingMore: false,
    selectedCard: null,
  }
}

function buildSearchSuccessState(
  current: SearchShellState,
  query: string,
  page: SimilarCardsPage
): SearchShellState {
  return {
    ...current,
    submittedQuery: query,
    results: page.items,
    hasMore: page.has_more,
    isLoading: false,
    isLoadingMore: false,
    selectedCard: null,
  }
}

function buildSearchFailureState(current: SearchShellState, query: string): SearchShellState {
  return {
    ...current,
    submittedQuery: query,
    results: [],
    hasMore: false,
    isLoading: false,
    isLoadingMore: false,
    selectedCard: null,
  }
}

function buildClearedState(current: SearchShellState): SearchShellState {
  return {
    ...current,
    draftQuery: '',
    submittedQuery: null,
    results: [],
    hasMore: false,
    isLoading: false,
    isLoadingMore: false,
    selectedCard: null,
  }
}

function getInitialState(): SearchShellState {
  const initialQuery = readSubmittedQueryFromUrl()

  if (!initialQuery) {
    return INITIAL_STATE
  }

  return {
    ...INITIAL_STATE,
    draftQuery: initialQuery,
    submittedQuery: initialQuery,
    isLoading: true,
  }
}

export function SearchShell() {
  const [state, setState] = useState<SearchShellState>(getInitialState)
  const activeRequestRef = useRef<AbortController | null>(null)
  const hasLoadedInitialQueryRef = useRef(false)
  const skipNextUrlWriteRef = useRef(state.submittedQuery !== null)

  const isHome = state.submittedQuery === null

  const handleDraftChange = (value: string) => {
    setState((current) => ({
      ...current,
      draftQuery: value,
    }))
  }

  const fetchFirstPage = useCallback(async (query: string, signal: AbortSignal) => {
    return searchOracleText(query, 0, RESULTS_PAGE_SIZE, state.filters, signal)
  }, [state.filters])

  const runSearch = useCallback(async (query: string) => {
    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setState((current) => buildSearchLoadingState(current, query))

    try {
      const page = await fetchFirstPage(query, controller.signal)

      if (controller.signal.aborted) return

      setState((current) => buildSearchSuccessState(current, query, page))
    } catch {
      if (controller.signal.aborted) return

      setState((current) => buildSearchFailureState(current, query))
    }
  }, [fetchFirstPage])

  const handleSubmit = (submittedValue?: string) => {
    const nextQuery = (submittedValue ?? state.draftQuery).trim()
    if (!nextQuery) return

    setState((current) => ({
      ...current,
      draftQuery: nextQuery,
    }))

    void runSearch(nextQuery)
  }

  const handleLoadMore = useCallback(async () => {
    if (!state.submittedQuery || state.isLoading || state.isLoadingMore || !state.hasMore) {
      return
    }

    const controller = new AbortController()

    setState((current) => ({
      ...current,
      isLoadingMore: true,
    }))

    try {
      const page = await searchOracleText(
        state.submittedQuery,
        state.results.length,
        RESULTS_PAGE_SIZE,
        state.filters,
        controller.signal
      )

      if (controller.signal.aborted) return

      setState((current) => ({
        ...current,
        results: [...current.results, ...page.items],
        hasMore: page.has_more,
        isLoadingMore: false,
      }))
    } catch {
      if (controller.signal.aborted) return

      setState((current) => ({
        ...current,
        isLoadingMore: false,
      }))
    }
  }, [
    state.filters,
    state.hasMore,
    state.isLoading,
    state.isLoadingMore,
    state.results.length,
    state.submittedQuery,
  ])

  const handleSelectCard = (card: SimilarCard) => {
    setState((current) => ({
      ...current,
      selectedCard:
        current.selectedCard &&
        current.selectedCard.id === card.id &&
        current.selectedCard.face_ix === card.face_ix &&
        current.selectedCard.image_side === card.image_side
          ? null
          : card,
    }))
  }

  const handleCloseOverlay = () => {
    setState((current) => ({
      ...current,
      selectedCard: null,
    }))
  }

  const handleReset = () => {
    activeRequestRef.current?.abort()
    writeSubmittedQueryToUrl(null)
    setState((current) => buildClearedState(current))
  }

  useEffect(() => {
    if (hasLoadedInitialQueryRef.current) return
    hasLoadedInitialQueryRef.current = true

    if (!state.submittedQuery) return

    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    void (async () => {
      try {
        const page = await fetchFirstPage(state.submittedQuery!, controller.signal)

        if (controller.signal.aborted) return

        setState((current) => buildSearchSuccessState(current, state.submittedQuery!, page))
      } catch {
        if (controller.signal.aborted) return

        setState((current) => buildSearchFailureState(current, state.submittedQuery!))
      }
    })()
  }, [fetchFirstPage, state.submittedQuery])

  useEffect(() => {
    if (!state.selectedCard) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setState((current) => ({
        ...current,
        selectedCard: null,
      }))
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [state.selectedCard])

  useEffect(() => {
    const handlePopState = () => {
      const nextQuery = readSubmittedQueryFromUrl()

      if (!nextQuery) {
        activeRequestRef.current?.abort()
        skipNextUrlWriteRef.current = true
        setState((current) => buildClearedState(current))
        return
      }

      skipNextUrlWriteRef.current = true
      setState((current) => ({
        ...current,
        draftQuery: nextQuery,
      }))

      void runSearch(nextQuery)
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [runSearch])

  useEffect(() => {
    if (skipNextUrlWriteRef.current) {
      skipNextUrlWriteRef.current = false
      return
    }

    if (state.submittedQuery === null) return
    writeSubmittedQueryToUrl(state.submittedQuery)
  }, [state.submittedQuery])

  return (
    <main className={`app-shell ${isHome ? 'app-shell-home' : 'app-shell-results'}`}>
      <div className="app-stripe" aria-hidden="true" />

      {isHome ? (
        <section className="home-shell" aria-label="Home state">
          <div className="home-wordmark">
            <h1 className="wordmark">
              <span className="wordmark-line">Oracle</span>
              <span className="wordmark-line">Tutor</span>
            </h1>
            <div className="home-rule" />
            <p className="home-kicker">find cards by meaning, not keywords.</p>
          </div>

          <div className="home-search-stage">
            <SearchBox
              value={state.draftQuery}
              onChange={handleDraftChange}
              onSubmit={handleSubmit}
              autoFocus
              showManaRail
            />
          </div>
        </section>
      ) : (
        <>
          <header className="topbar">
            <button type="button" className="topbar-logo" onClick={handleReset}>
              <span className="topbar-logo-text topbar-logo-text-full">Oracle Tutor</span>
              <span className="topbar-logo-text topbar-logo-text-compact">OT</span>
            </button>
            <div className="topbar-status">
              <SearchBox
                className="topbar-search-box"
                value={state.draftQuery}
                onChange={handleDraftChange}
                onSubmit={handleSubmit}
                autoFocus={false}
                showManaRail={false}
              />
            </div>
          </header>

          <section className="query-band" aria-label="Results summary">
            <div className="query-band-main">
              <p className="eyebrow">Results</p>
              <h2 className="query-title">{state.submittedQuery}</h2>
            </div>
            <div className="query-band-meta">
              {!state.isLoading ? (
                <span className="query-count">
                  {state.results.length}
                  {state.hasMore || state.isLoadingMore ? '+' : ''} cards
                </span>
              ) : null}
              <span className="query-hint">Select a card to open the detail rail.</span>
            </div>
          </section>

          <section className="results-main" aria-label="Results state">
            {state.isLoading ? <p className="results-feedback">Loading results...</p> : null}
            {!state.isLoading && state.results.length === 0 ? (
              <p className="results-feedback">No cards matched this search.</p>
            ) : null}
            {state.results.length > 0 ? (
              <div className="results-layout">
                <ResultsGrid
                  cards={state.results}
                  hasMore={state.hasMore}
                  isLoadingMore={state.isLoadingMore}
                  selectedCardId={state.selectedCard?.id ?? null}
                  onCardSelect={handleSelectCard}
                  onLoadMore={handleLoadMore}
                />
                {state.selectedCard ? (
                  <CardOverlay card={state.selectedCard} onClose={handleCloseOverlay} />
                ) : null}
              </div>
            ) : null}
          </section>
        </>
      )}
    </main>
  )
}
