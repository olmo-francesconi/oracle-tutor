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
  const isResults = !isHome

  const handleDraftChange = (value: string) => {
    setState((current) => ({
      ...current,
      draftQuery: value,
    }))
  }

  const fetchFirstPage = useCallback(async (query: string, signal: AbortSignal) => {
    return searchOracleText(
      query,
      0,
      RESULTS_PAGE_SIZE,
      state.filters,
      signal
    )
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
      selectedCard: card,
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
    <main className="app-shell">
      <section className="shell-panel">
        <header className="shell-header">
          <p className="eyebrow">Frontend V2</p>
          <h1 className="wordmark">
            Oracle <span className="wordmark-divider">/</span> Tutor
          </h1>
          <p className="shell-copy">
            One shell, one state owner, one complex subsystem. The rest stays intentionally plain.
          </p>
        </header>

        <section className="state-switcher" aria-label="Search controls">
          <SearchBox
            value={state.draftQuery}
            onChange={handleDraftChange}
            onSubmit={handleSubmit}
            autoFocus
          />

          <div className="control-actions">
            <button type="button" onClick={() => handleSubmit()} className="shell-button">
              Show Results
            </button>
            <button type="button" onClick={handleReset} className="shell-button shell-button-secondary">
              Reset
            </button>
          </div>
        </section>

        <section className="shell-stage">
          {isHome ? (
            <section className="view-panel" aria-label="Home state">
              <p className="eyebrow">Home State</p>
              <p className="view-copy">
                The search box owns the specialized UX. The shell just moves from prompt to results.
              </p>
              <p className="view-copy">
                Mana symbols still frame the interface:
                {' '}
                <span className="mana-sample">
                  <i className="ms ms-w" aria-hidden="true" />
                  <i className="ms ms-u" aria-hidden="true" />
                  <i className="ms ms-b" aria-hidden="true" />
                  <i className="ms ms-r" aria-hidden="true" />
                  <i className="ms ms-g" aria-hidden="true" />
                </span>
              </p>
            </section>
          ) : null}

          {isResults ? (
            <section className="view-panel" aria-label="Results state">
              <p className="eyebrow">Results State</p>
              <p className="view-copy">
                Submitted query:
                {' '}
                <strong>{state.submittedQuery}</strong>
              </p>
              {!state.isLoading && state.results.length > 0 ? (
                <p className="results-summary">Click any card to inspect it in the side panel.</p>
              ) : null}
              {state.isLoading ? <p className="view-copy">Loading results...</p> : null}
              {!state.isLoading && state.results.length === 0 ? (
                <p className="view-copy">No cards matched this search.</p>
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
          ) : null}
        </section>
      </section>
    </main>
  )
}
