import { useCallback, useMemo, useState } from 'react'
import { useApiReadyState } from '../lib/apiReadyContext'
import { getApiDownMessage, getSearchErrorMessage, isApiDownError } from './searchShellState'
import { getActiveFilterCount, normalizeFilterState } from '../lib/filters'
import { readSearchStateFromUrl, writeSearchStateToUrl } from '../lib/urlState'
import type { CardMatch, FilterState, OracleSamples, SimilarCard } from '../types/api'
import type { PinnedCard, SearchShellState } from '../types/ui'
import { CardDetailOverlay } from '../components/CardDetailOverlay'
import { DenseTextBackground } from '../components/background/DenseTextBackground'
import { ApiDownOverlay } from '../components/errors/ApiDownOverlay'
import { HomeView } from './HomeView'
import { ResultsView } from './ResultsView'
import { WaitingView } from './WaitingView'

const LEFT_STRIPE_WIDTH_PX = 6
import { useCardQuery } from './useCardQuery'
import { useDocumentHead } from './useDocumentHead'
import { useOracleSamplesQuery } from './useOracleSamplesQuery'
import { useSearchQuery } from './useSearchQuery'
import { useSimilarQuery } from './useSimilarQuery'
import { useUrlSync } from './useUrlSync'
import { useViewport } from './useViewport'

const EMPTY_ORACLE_SAMPLES: OracleSamples = { texts: [], terms: [] }

type ShellUiState = {
  draftQuery: string
  submittedQuery: string | null
  pinnedCard: PinnedCard | null
  filters: FilterState
}

const INITIAL_UI_STATE: ShellUiState = {
  draftQuery: '',
  submittedQuery: null,
  pinnedCard: null,
  filters: {},
}

function getInitialUiState(): ShellUiState {
  const urlState = readSearchStateFromUrl()

  if (urlState.pinnedCard) {
    return {
      ...INITIAL_UI_STATE,
      pinnedCard: { ...urlState.pinnedCard, name: '' },
      filters: urlState.filters,
    }
  }

  if (urlState.query) {
    return {
      draftQuery: urlState.query,
      submittedQuery: urlState.query,
      pinnedCard: null,
      filters: urlState.filters,
    }
  }

  return INITIAL_UI_STATE
}

type DetailTarget = {
  oracle_id: string
  similarity: number | null
}

export function SearchShell() {
  const [ui, setUi] = useState<ShellUiState>(getInitialUiState)
  const [showFilters, setShowFilters] = useState(false)
  const [detail, setDetail] = useState<DetailTarget | null>(null)
  const [lastTextQuery, setLastTextQuery] = useState<string | null>(null)
  const viewport = useViewport()
  const apiReadyState = useApiReadyState()
  const apiReady = apiReadyState.ready

  const oracleSamplesQuery = useOracleSamplesQuery()
  const cardQuery = useCardQuery(ui.pinnedCard?.oracle_id)
  const searchQuery = useSearchQuery(ui.pinnedCard ? null : ui.submittedQuery, ui.filters)
  const similarQuery = useSimilarQuery(ui.pinnedCard, ui.filters)

  const activeQuery = ui.pinnedCard ? similarQuery : searchQuery
  const oracleSamples = oracleSamplesQuery.data ?? EMPTY_ORACLE_SAMPLES

  // When the URL drops us straight into card mode the pinned_card.name is
  // empty until useCardQuery resolves. Derive the display name at render
  // instead of writing it back into state (avoids setState-in-effect).
  const resolvedPinnedName = ui.pinnedCard
    ? ui.pinnedCard.name || cardQuery.data?.name || ''
    : ''
  const displayDraft = ui.pinnedCard && !ui.draftQuery ? resolvedPinnedName : ui.draftQuery
  const displaySubmitted = ui.pinnedCard ? resolvedPinnedName : ui.submittedQuery

  const pinnedSummary = useMemo(() => {
    if (!ui.pinnedCard || !cardQuery.data) return null
    const card = cardQuery.data
    const faceIx = ui.pinnedCard.face_ix ?? 0
    const face = card.faces?.[faceIx] ?? card.faces?.[0] ?? null
    return {
      oracleText: card.oracle_text ?? face?.oracle_text ?? null,
    }
  }, [ui.pinnedCard, cardQuery.data])

  const results: SimilarCard[] = useMemo(
    () => activeQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [activeQuery.data]
  )

  const apiDownError = useMemo(() => {
    for (const q of [activeQuery, oracleSamplesQuery]) {
      if (q.isError && isApiDownError(q.error)) return q.error
    }
    return null
  }, [activeQuery, oracleSamplesQuery])

  const searchErrorMessage =
    activeQuery.isError && !isApiDownError(activeQuery.error)
      ? getSearchErrorMessage(activeQuery.error)
      : null

  const shellState: SearchShellState = {
    draftQuery: displayDraft,
    submittedQuery: displaySubmitted,
    pinnedCard: ui.pinnedCard ? { ...ui.pinnedCard, name: resolvedPinnedName } : null,
    filters: ui.filters,
    error: searchErrorMessage,
    results,
    hasMore: activeQuery.hasNextPage ?? false,
    isLoading: activeQuery.isLoading && activeQuery.isFetching,
    isLoadingMore: activeQuery.isFetchingNextPage,
  }

  const isHome = ui.submittedQuery === null && ui.pinnedCard === null
  const isSemanticWarming = !apiReady && !isHome
  const activeFilterCount = getActiveFilterCount(ui.filters)
  const hasOracleBackground = oracleSamples.texts.length > 0

  const handleDraftChange = useCallback((value: string) => {
    setUi((current) => ({ ...current, draftQuery: value }))
  }, [])

  const handleSubmit = useCallback(
    (submittedValue?: string) => {
      const nextQuery = (submittedValue ?? ui.draftQuery).trim()
      if (!nextQuery) return
      setLastTextQuery(null)
      setUi((current) => ({
        ...current,
        draftQuery: nextQuery,
        submittedQuery: nextQuery,
        pinnedCard: null,
      }))
    },
    [ui.draftQuery]
  )

  const handleCardSelect = useCallback(
    (card: CardMatch) => {
      if (!card.oracle_id) return
      if (ui.submittedQuery && !ui.pinnedCard) setLastTextQuery(ui.submittedQuery)
      setUi((current) => ({
        ...current,
        draftQuery: card.name,
        submittedQuery: null,
        pinnedCard: { oracle_id: card.oracle_id!, face_ix: card.face_ix, name: card.name },
      }))
    },
    [ui.submittedQuery, ui.pinnedCard]
  )

  const handleFiltersChange = useCallback((nextFilters: FilterState) => {
    const normalized = normalizeFilterState(nextFilters)
    setUi((current) => ({ ...current, filters: normalized }))
  }, [])

  const handleClearFilters = useCallback(() => {
    setUi((current) => ({ ...current, filters: {} }))
  }, [])

  const handleCardOpen = useCallback((card: SimilarCard) => {
    if (!card.oracle_id) return
    setDetail({
      oracle_id: card.oracle_id,
      similarity: typeof card.similarity === 'number' ? card.similarity : null,
    })
  }, [])

  const handleDetailClose = useCallback(() => {
    setDetail(null)
  }, [])

  const handlePinnedTitleClick = useCallback(() => {
    if (!ui.pinnedCard) return
    setDetail({ oracle_id: ui.pinnedCard.oracle_id, similarity: null })
  }, [ui.pinnedCard])

  const handleDetailFindSimilar = useCallback(
    (oracleId: string, name: string, faceIx: number) => {
      setDetail(null)
      setUi((current) => ({
        ...current,
        draftQuery: name,
        submittedQuery: null,
        pinnedCard: { oracle_id: oracleId, face_ix: faceIx, name },
      }))
    },
    []
  )

  const handleRestoreTextQuery = useCallback(() => {
    if (!lastTextQuery) return
    setUi((current) => ({
      ...current,
      draftQuery: lastTextQuery,
      submittedQuery: lastTextQuery,
      pinnedCard: null,
    }))
    setLastTextQuery(null)
  }, [lastTextQuery])

  const handleLoadMore = useCallback(() => {
    if (activeQuery.hasNextPage && !activeQuery.isFetchingNextPage) {
      void activeQuery.fetchNextPage()
    }
  }, [activeQuery])

  const handleReset = useCallback(() => {
    writeSearchStateToUrl(null, {})
    setDetail(null)
    setLastTextQuery(null)
    setUi(INITIAL_UI_STATE)
  }, [])

  const handleRetryApi = useCallback(() => {
    if (oracleSamplesQuery.isError) void oracleSamplesQuery.refetch()
    if (activeQuery.isError) void activeQuery.refetch()
  }, [activeQuery, oracleSamplesQuery])

  useUrlSync(ui, setUi)

  useDocumentHead({
    isHome,
    submittedQuery: ui.submittedQuery,
    pinnedCard: ui.pinnedCard,
    pinnedCardData: cardQuery.data ?? null,
    filters: ui.filters,
  })

  return (
    <main
      className={[
        'relative isolate min-h-screen bg-ot-bg',
        isHome || isSemanticWarming
          ? 'grid place-items-center px-6 pb-16 pl-11 pt-12 max-[720px]:px-4 max-[720px]:pb-12 max-[720px]:pl-[30px] max-[720px]:pt-8'
          : '',
      ].join(' ')}
    >
      <DenseTextBackground
        texts={oracleSamples.texts}
        viewport={viewport}
        isVisible={hasOracleBackground}
        leftInset={LEFT_STRIPE_WIDTH_PX}
      />
      {isHome ? (
        <HomeView
          draftQuery={displayDraft}
          oracleSamples={oracleSamples}
          viewport={viewport}
          hasOracleBackground={hasOracleBackground}
          onDraftChange={handleDraftChange}
          onSubmit={handleSubmit}
          onCardSelect={handleCardSelect}
        />
      ) : isSemanticWarming ? (
        <WaitingView attempts={apiReadyState.attempts} error={apiReadyState.error} />
      ) : (
        <ResultsView
          state={shellState}
          showFilters={showFilters}
          activeFilterCount={activeFilterCount}
          lastTextQuery={lastTextQuery}
          pinnedSummary={pinnedSummary}
          onDraftChange={handleDraftChange}
          onSubmit={handleSubmit}
          onCardSelect={handleCardSelect}
          onReset={handleReset}
          onToggleFilters={() => setShowFilters((v) => !v)}
          onFiltersChange={handleFiltersChange}
          onClearFilters={handleClearFilters}
          onLoadMore={handleLoadMore}
          onCardOpen={handleCardOpen}
          onTitleClick={handlePinnedTitleClick}
          onRestoreTextQuery={handleRestoreTextQuery}
        />
      )}
      <CardDetailOverlay
        oracleId={detail?.oracle_id ?? null}
        similarity={detail?.similarity ?? null}
        onClose={handleDetailClose}
        onFindSimilar={handleDetailFindSimilar}
      />
      {apiDownError ? (
        <ApiDownOverlay
          message={getApiDownMessage(apiDownError)}
          isRetrying={activeQuery.isFetching || oracleSamplesQuery.isFetching}
          onRetry={handleRetryApi}
        />
      ) : null}
    </main>
  )
}
