import { useCallback, useEffect, useRef, useState } from 'react'
import { CardOverlay } from '../components/CardOverlay'
import { ResultsGrid } from '../components/ResultsGrid'
import { SearchBox } from '../components/SearchBox/SearchBox'
import { DenseTextBackground } from '../components/background/DenseTextBackground'
import { HomeEditorialText } from '../components/background/HomeEditorialText'
import { getOracleSamples, searchOracleText } from '../lib/api'
import { readSubmittedQueryFromUrl, writeSubmittedQueryToUrl } from '../lib/urlState'
import type { OracleSamples, SimilarCard, SimilarCardsPage } from '../types/api'
import type { SearchShellState } from '../types/ui'

const RESULTS_PAGE_SIZE = 24
const LEFT_STRIPE_WIDTH_PX = 6

type ViewportSize = {
  width: number
  height: number
}

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

function getSelectedCardKey(card: SimilarCard | null): string | null {
  if (!card) return null
  return `${card.id}-${card.face_ix}-${card.image_side}`
}

export function SearchShell() {
  const [state, setState] = useState<SearchShellState>(getInitialState)
  const [oracleSamples, setOracleSamples] = useState<OracleSamples>(EMPTY_ORACLE_SAMPLES)
  const [viewport, setViewport] = useState<ViewportSize>(getViewportSize)
  const activeRequestRef = useRef<AbortController | null>(null)
  const hasLoadedInitialQueryRef = useRef(false)
  const skipNextUrlWriteRef = useRef(state.submittedQuery !== null)
  const resizeFrameRef = useRef<number | null>(null)

  const isHome = state.submittedQuery === null
  const selectedCardKey = getSelectedCardKey(state.selectedCard)
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

  const runSearch = useCallback(async (query: string) => {
    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setState((current) => buildSearchLoadingState(current, query))

    try {
      const page = await fetchFirstPage(query, state.filters, controller.signal)

      if (controller.signal.aborted) return

      setState((current) => buildSearchSuccessState(current, query, page))
    } catch {
      if (controller.signal.aborted) return

      setState((current) => buildSearchFailureState(current, query))
    }
  }, [fetchFirstPage, state.filters])

  const handleSubmit = useCallback((submittedValue?: string) => {
    const nextQuery = (submittedValue ?? state.draftQuery).trim()
    if (!nextQuery) return

    setState((current) => ({
      ...current,
      draftQuery: nextQuery,
    }))

    void runSearch(nextQuery)
  }, [runSearch, state.draftQuery])

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

  const handleSelectCard = useCallback((card: SimilarCard) => {
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
  }, [])

  const handleCloseOverlay = useCallback(() => {
    setState((current) => ({
      ...current,
      selectedCard: null,
    }))
  }, [])

  const handleReset = useCallback(() => {
    activeRequestRef.current?.abort()
    writeSubmittedQueryToUrl(null)
    setState((current) => buildClearedState(current))
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    void (async () => {
      const nextSamples = await getOracleSamples(controller.signal)

      if (!controller.signal.aborted) {
        setOracleSamples(nextSamples)
      }
    })()

    return () => controller.abort()
  }, [])

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

    if (!state.submittedQuery) return
    const submittedQuery = state.submittedQuery

    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    void (async () => {
      try {
        const page = await fetchFirstPage(submittedQuery, state.filters, controller.signal)

        if (controller.signal.aborted) return

        setState((current) => buildSearchSuccessState(current, submittedQuery, page))
      } catch {
        if (controller.signal.aborted) return

        setState((current) => buildSearchFailureState(current, submittedQuery))
      }
    })()
  }, [fetchFirstPage, state.filters, state.submittedQuery])

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
    <main
      className={[
        'relative min-h-screen bg-ot-bg',
        isHome ? 'grid place-items-center px-6 pb-16 pl-11 pt-12 max-[720px]:px-4 max-[720px]:pb-12 max-[720px]:pl-[30px] max-[720px]:pt-8' : '',
      ].join(' ')}
    >
      <DenseTextBackground
        texts={oracleSamples.texts}
        viewport={viewport}
        isVisible={hasOracleBackground}
        leftInset={LEFT_STRIPE_WIDTH_PX}
      />
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
              autoFocus
              showManaRail
              variant="home"
            />
          </div>
        </section>
      ) : (
        <>
          <header className="sticky top-0 z-30 grid min-h-[58px] grid-cols-[clamp(148px,16vw,176px)_minmax(0,1fr)] items-stretch border-b-2 border-ot-ink bg-ot-bg max-[720px]:grid-cols-[auto_minmax(0,1fr)]">
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
                autoFocus={false}
                showManaRail={false}
                variant="topbar"
              />
            </div>
          </header>

          <section
            className="relative z-20 grid grid-cols-[minmax(0,1fr)_auto] items-end gap-x-8 gap-y-[18px] border-b-2 border-ot-ink bg-ot-bg px-6 pb-[18px] pl-[38px] pr-6 pt-4 max-[720px]:grid-cols-1 max-[720px]:gap-[10px] max-[720px]:px-4 max-[720px]:pb-4 max-[720px]:pl-6 max-[720px]:pt-[14px]"
            aria-label="Results summary"
          >
            <div className="grid max-w-[min(34rem,100%)] gap-1 max-[720px]:gap-0.5">
              <p className="eyebrow">Results</p>
              <h2 className="m-0 font-display text-[clamp(2.2rem,4.4vw,3.35rem)] font-black uppercase leading-[0.9] tracking-[-0.02em]">
                {state.submittedQuery}
              </h2>
            </div>
            <div className="grid min-w-[13rem] justify-items-end gap-1.5 self-center max-[720px]:min-w-0 max-[720px]:justify-items-start">
              {!state.isLoading ? (
                <span className="m-0 text-xs uppercase tracking-[0.11em] text-ot-muted">
                  {state.results.length}
                  {state.hasMore || state.isLoadingMore ? '+' : ''} cards
                </span>
              ) : null}
              <span className="m-0 text-xs uppercase tracking-[0.11em] text-ot-muted">
                Select a card to open the detail rail.
              </span>
            </div>
          </section>

          <section
            className="px-6 pb-14 pl-[38px] pr-6 pt-6 max-[720px]:px-4 max-[720px]:pl-6"
            aria-label="Results state"
          >
            {state.isLoading ? (
              <p className="m-0 text-xs uppercase tracking-[0.11em] text-ot-muted">Loading results...</p>
            ) : null}
            {!state.isLoading && state.results.length === 0 ? (
              <p className="m-0 text-xs uppercase tracking-[0.11em] text-ot-muted">No cards matched this search.</p>
            ) : null}
            {state.results.length > 0 ? (
              <div className="grid items-start gap-7 [grid-template-columns:minmax(0,1fr)_340px] max-[900px]:grid-cols-1">
                <ResultsGrid
                  cards={state.results}
                  hasMore={state.hasMore}
                  isLoadingMore={state.isLoadingMore}
                  selectedCardKey={selectedCardKey}
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
