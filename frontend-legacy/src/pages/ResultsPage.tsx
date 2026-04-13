import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Helmet } from 'react-helmet-async'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { FunnelIcon } from '@phosphor-icons/react'
import { getCard, getOracleSamples, getSimilarCards, searchOracleText } from '../api'
import { CardGrid } from '../components/CardGrid'
import { CardOverlay } from '../components/CardOverlay'
import { FilterBar } from '../components/FilterBar'
import { HomeTextBackground } from '../components/HomeTextBackground'
import { PageSEO } from '../components/PageSEO'
import { SymbolText } from '../components/SymbolText'
import { UnifiedSearchBox } from '../components/UnifiedSearchBox'
import { getBaseUrl } from '../lib/seo'
import type { FilterState, SimilarCard } from '../types'
import { getCardImageUrl, getImageSideForFace } from '../utils'

const RESULTS_PAGE_SIZE = 60
const HOME_LEFT_INSET = 6
const MIN_HOME_COMPOSITION_WIDTH = 360
const TOP_BAR_HEIGHT = 56
const DETAIL_BAND_HEIGHT = 46

function getActiveFilterCount(filters: FilterState): number {
  return Object.keys(filters).filter(
    (key) => filters[key as keyof FilterState] !== undefined
  ).length
}

function getSelectedCardId(card: SimilarCard | null): string | null {
  return card ? `${card.oracle_id}:${card.face_ix}` : null
}

function getCurrentCardIndex(
  cards: SimilarCard[],
  selectedCard: SimilarCard | null
): number {
  if (!selectedCard) return -1

  return cards.findIndex(
    (card) =>
      card.oracle_id === selectedCard.oracle_id &&
      card.face_ix === selectedCard.face_ix
  )
}

function SearchResultsOverlay({
  selectedCard,
  cards,
  onClose,
  onSelect,
}: {
  selectedCard: SimilarCard | null
  cards: SimilarCard[]
  onClose: () => void
  onSelect: (card: SimilarCard) => void
}) {
  const currentIndex = getCurrentCardIndex(cards, selectedCard)

  if (!selectedCard) return null

  return (
    <CardOverlay
      card={selectedCard}
      onClose={onClose}
      hasPrev={currentIndex > 0}
      hasNext={currentIndex >= 0 && currentIndex < cards.length - 1}
      onPrev={() => onSelect(cards[currentIndex - 1])}
      onNext={() => onSelect(cards[currentIndex + 1])}
    />
  )
}

function CardResultsOverlay({
  selectedCard,
  cards,
  routeId,
  onClose,
  onSelect,
}: {
  selectedCard: SimilarCard | null
  cards: SimilarCard[]
  routeId: string
  onClose: () => void
  onSelect: (selection: { routeId: string; card: SimilarCard }) => void
}) {
  const currentIndex = getCurrentCardIndex(cards, selectedCard)

  if (!selectedCard) return null

  return (
    <CardOverlay
      card={selectedCard}
      onClose={onClose}
      hasPrev={currentIndex > 0}
      hasNext={currentIndex >= 0 && currentIndex < cards.length - 1}
      onPrev={() => onSelect({ routeId, card: cards[currentIndex - 1] })}
      onNext={() => onSelect({ routeId, card: cards[currentIndex + 1] })}
    />
  )
}

// ── Search mode ──────────────────────────────────────────────────────────────

function SearchMode({ query }: { query: string }) {
  const [selectedCard, setSelectedCard] = useState<SimilarCard | null>(null)
  const [filters, setFilters] = useState<FilterState>({})
  const [showFilters, setShowFilters] = useState(false)

  const {
    data: searchData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteQuery({
    queryKey: ['oracle-search', query, filters],
    queryFn: ({ pageParam = 0 }) =>
      searchOracleText(query, pageParam, RESULTS_PAGE_SIZE, filters),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.has_more ? allPages.length * RESULTS_PAGE_SIZE : undefined,
    enabled: !!query,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
  })

  const cards = useMemo(
    () => searchData?.pages.flatMap((page) => page.items) ?? [],
    [searchData]
  )

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedCard(null)
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [])

  const activeFilterCount = getActiveFilterCount(filters)

  const { pathname, search } = useLocation()

  return (
    <>
      <PageSEO
        title={query ? `"${query}" — Oracle Tutor` : 'Search — Oracle Tutor'}
        description={
          query
            ? `Search results for «${query}». Find Magic: The Gathering cards by semantic meaning.`
            : 'Search for Magic: The Gathering cards by what they do.'
        }
        path={`${pathname}${search}`}
      />

      <SearchResultsOverlay
        selectedCard={selectedCard}
        cards={cards}
        onClose={() => setSelectedCard(null)}
        onSelect={setSelectedCard}
      />

      <ResultsPageShell
        searchBox={
          <UnifiedSearchBox
            key={query}
            enableTypeAhead
            size="topBar"
            initialValue={query}
            className="h-full w-full"
            onTypeAheadTrigger={() => window.scrollTo({ top: 0 })}
          />
        }
        filters={filters}
        onFilterChange={setFilters}
        showFilters={showFilters}
        activeFilterCount={activeFilterCount}
        onToggleFilters={() => setShowFilters((value) => !value)}
      >
        {query && (
          <DetailBand accent>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3 sm:px-6 sm:py-3.5">
              <h2 className="font-display text-[18px] leading-none font-[900] tracking-[-0.02em] text-[#111111] uppercase sm:text-[20px]">
                <SymbolText text={query} />
              </h2>
              {!isLoading && (
                <span className="font-mono text-[11px] text-[#7A7670]">
                  {cards.length}
                  {hasNextPage || isFetchingNextPage ? '+' : ''} results
                </span>
              )}
            </div>
          </DetailBand>
        )}

        <div className="min-h-0 flex-1" style={{ paddingTop: query ? DETAIL_BAND_HEIGHT : 0 }}>
          <ResultsSurface>
            <CardGrid
              cards={cards}
              isLoading={isLoading}
              isFetchingNextPage={isFetchingNextPage}
              hasNextPage={!!hasNextPage}
              fetchNextPage={fetchNextPage}
              onCardClick={setSelectedCard}
              showCountPlus={!!hasNextPage || isFetchingNextPage}
              selectedCardId={getSelectedCardId(selectedCard)}
              searchQuery={query}
              showFloatingFilters={false}
            />
          </ResultsSurface>
        </div>
      </ResultsPageShell>
    </>
  )
}

// ── Card mode ─────────────────────────────────────────────────────────────────

function CardMode({ id }: { id: string }) {
  const [searchParams] = useSearchParams()
  const requestedFace = Number(searchParams.get('face') ?? '0')
  const selectedFaceIx =
    Number.isInteger(requestedFace) && requestedFace >= 0 ? requestedFace : 0

  const [selected, setSelected] = useState<{
    routeId: string
    card: SimilarCard
  } | null>(null)
  const selectedCard = selected?.routeId === id ? selected.card : null
  const [filters, setFilters] = useState<FilterState>({})
  const [showFilters, setShowFilters] = useState(false)

  const {
    data: card,
    isLoading: cardLoading,
    error: cardError,
  } = useQuery({
    queryKey: ['card', id],
    queryFn: () => getCard(id),
    enabled: !!id,
  })

  const {
    data: similarData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: similarLoading,
  } = useInfiniteQuery({
    queryKey: ['similar', id, selectedFaceIx, filters],
    queryFn: ({ pageParam = 0 }) =>
      getSimilarCards(id, selectedFaceIx, pageParam, RESULTS_PAGE_SIZE, filters),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.has_more ? allPages.length * RESULTS_PAGE_SIZE : undefined,
    enabled: !!id,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
  })

  const similarCards = useMemo(
    () => similarData?.pages.flatMap((page) => page.items) ?? [],
    [similarData]
  )

  const navigableCards = useMemo(() => {
    if (!card) return similarCards
    const imageSide = getImageSideForFace(card.layout, selectedFaceIx)
    return [
      {
        ...card,
        face_ix: selectedFaceIx,
        image_side: imageSide,
        similarity: 1,
      } as SimilarCard,
      ...similarCards,
    ]
  }, [card, selectedFaceIx, similarCards])

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null)
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [])

  useEffect(() => {
    const currentIndex = getCurrentCardIndex(navigableCards, selectedCard)

    if (
      selectedCard &&
      currentIndex >= 0 &&
      currentIndex >= navigableCards.length - 10 &&
      hasNextPage &&
      !isFetchingNextPage
    ) {
      fetchNextPage()
    }
  }, [
    selectedCard,
    navigableCards,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  ])

  const activeFilterCount = getActiveFilterCount(filters)

  if (cardLoading)
    return (
      <div className="font-display flex h-screen items-center justify-center text-sm tracking-wider text-[#7A7670] uppercase">
        Loading…
      </div>
    )
  if (cardError || !card)
    return (
      <div className="font-display flex h-screen items-center justify-center text-sm tracking-wider text-[#7A7670] uppercase">
        Card not found.
      </div>
    )

  const selectedFace = card.faces?.[selectedFaceIx] ?? card.faces?.[0]
  const selectedImageSide = getImageSideForFace(card.layout, selectedFaceIx)
  const displayName = selectedFace?.name ?? card.name
  const displayType = selectedFace?.type_line || card.type_line
  const displayMana = selectedFace?.mana_cost || card.mana_cost
  const displayOracle = selectedFace?.oracle_text || card.oracle_text

  const mainCardImageUrl = getCardImageUrl({
    ...card,
    image_side: selectedImageSide,
  })
  const cardDescription = [displayType, displayOracle]
    .filter(Boolean)
    .join('. ')
  const truncatedDescription =
    cardDescription.length > 160
      ? `${cardDescription.slice(0, 157)}...`
      : cardDescription

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'CreativeWork',
    name: displayName,
    description:
      truncatedDescription || `${card.name} — Magic: The Gathering card.`,
    image: mainCardImageUrl,
    url: `${getBaseUrl()}/card/${id}`,
  }

  return (
    <div className="flex min-h-screen w-full flex-col bg-[#F0EDE6]">
      <PageSEO
        title={`${card.name} - Oracle Tutor`}
        description={
          truncatedDescription || `${card.name} — Magic: The Gathering card.`
        }
        path={`/card/${id}`}
        image={mainCardImageUrl}
      />
      <Helmet>
        <script type="application/ld+json">{JSON.stringify(jsonLd)}</script>
      </Helmet>

      <CardResultsOverlay
        selectedCard={selectedCard}
        cards={navigableCards}
        routeId={id}
        onClose={() => setSelected(null)}
        onSelect={setSelected}
      />

      <ResultsPageShell
        searchBox={
          <UnifiedSearchBox
            key={displayName}
            enableTypeAhead
            size="topBar"
            initialValue={displayName}
            className="h-full w-full"
            onTypeAheadTrigger={() => window.scrollTo({ top: 0 })}
          />
        }
        filters={filters}
        onFilterChange={setFilters}
        showFilters={showFilters}
        activeFilterCount={activeFilterCount}
        onToggleFilters={() => setShowFilters((value) => !value)}
      >
        <DetailBand accent>
          <div className="flex min-w-0 flex-1 items-center gap-2 px-4 py-3 sm:gap-3 sm:px-6 sm:py-3.5">
            <h1 className="font-display min-w-0 truncate text-[18px] leading-none font-[900] tracking-[-0.02em] text-[#111111] uppercase sm:shrink-0 sm:text-[20px]">
              {displayName}
            </h1>
            {displayMana && (
              <>
                <span className="shrink-0 text-[#CCCCCC]" aria-hidden>·</span>
                <span className="font-mono shrink-0 text-[11px] text-[#7A7670]">
                  <SymbolText text={displayMana} />
                </span>
              </>
            )}
            {displayType && (
              <>
                <span className="shrink-0 text-[#CCCCCC]" aria-hidden>·</span>
                <span className="font-mono min-w-0 truncate text-[11px] text-[#7A7670]">
                  {displayType}
                </span>
              </>
            )}
            {displayOracle && (
              <>
                <span className="hidden shrink-0 text-[#CCCCCC] sm:block" aria-hidden>·</span>
                <span className="font-mono hidden min-w-0 truncate text-[11px] text-[#7A7670] sm:block">
                  <SymbolText text={displayOracle} />
                </span>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={() =>
              setSelected({
                routeId: id,
                card: {
                  ...card,
                  face_ix: selectedFaceIx,
                  image_side: selectedImageSide,
                  similarity: 1,
                } as SimilarCard,
              })
            }
            className="font-mono flex shrink-0 items-center border-l-2 border-[#111111] px-4 text-[11px] uppercase tracking-[0.08em] text-[#7A7670] transition-colors hover:bg-[#111111] hover:text-[#F0EDE6] sm:px-5"
          >
            View card ↗
          </button>
        </DetailBand>

        <div className="min-h-0 flex-1" style={{ paddingTop: DETAIL_BAND_HEIGHT }}>
          <ResultsSurface>
            <CardGrid
              cards={similarCards}
              isLoading={similarLoading}
              isFetchingNextPage={isFetchingNextPage}
              hasNextPage={!!hasNextPage}
              fetchNextPage={fetchNextPage}
              onCardClick={(similarCard) =>
                setSelected({ routeId: id, card: similarCard })
              }
              showCountPlus={!!hasNextPage || isFetchingNextPage}
              selectedCardId={getSelectedCardId(selectedCard)}
              searchQuery={id}
              filters={filters}
              onFilterChange={setFilters}
              showFloatingFilters={false}
            />
          </ResultsSurface>
        </div>
      </ResultsPageShell>
    </div>
  )
}

function ResultsSurface({ children }: { children: React.ReactNode }) {
  const { data: oracleSamples, isSuccess: hasOracleSamples } = useQuery({
    queryKey: ['oracle-samples'],
    queryFn: getOracleSamples,
    staleTime: Infinity,
    gcTime: Infinity,
  })

  const backgroundTexts = oracleSamples?.texts ?? []
  const isBackgroundLoaded = hasOracleSamples && backgroundTexts.length > 0

  return (
    <div className="relative min-h-0 flex-1 overflow-hidden">
      <HomeTextBackground
        texts={backgroundTexts}
        isLoaded={isBackgroundLoaded}
        leftInset={HOME_LEFT_INSET}
        minTotalWidth={MIN_HOME_COMPOSITION_WIDTH}
        fixedToViewport
      />
      <div className="relative z-10 h-full">
        {children}
      </div>
    </div>
  )
}

function ResultsPageShell({
  searchBox,
  filters,
  onFilterChange,
  showFilters,
  activeFilterCount,
  onToggleFilters,
  children,
}: {
  searchBox: React.ReactNode
  filters: FilterState
  onFilterChange: (filters: FilterState) => void
  showFilters: boolean
  activeFilterCount: number
  onToggleFilters: () => void
  children: React.ReactNode
}) {
  const [filterStripHeight, setFilterStripHeight] = useState(0)
  const chromeHeight = TOP_BAR_HEIGHT + (showFilters ? filterStripHeight : 0)

  return (
    <div className="min-h-screen bg-[#F0EDE6]">
      <div className="fixed inset-x-0 top-0 z-40">
        <TopBar
          center={searchBox}
          showFilters={showFilters}
          activeFilterCount={activeFilterCount}
          onToggleFilters={onToggleFilters}
        />

        {showFilters && (
          <FilterStrip
            filters={filters}
            onFilterChange={onFilterChange}
            onHeightChange={setFilterStripHeight}
          />
        )}
      </div>

      <div
        className="flex min-h-screen flex-col bg-[#F0EDE6]"
        style={{ paddingTop: chromeHeight, ['--results-top-offset' as string]: `${chromeHeight}px` }}
      >
        {children}
      </div>
    </div>
  )
}

// ── Shared chrome ─────────────────────────────────────────────────────────────

function DetailBand({ accent, children }: { accent?: boolean; children: React.ReactNode }) {
  return (
    <div
      className="fixed inset-x-0 z-30 flex items-stretch border-b-2 border-[#111111] bg-[#F0EDE6]"
      style={{ top: 'var(--results-top-offset, 56px)', minHeight: DETAIL_BAND_HEIGHT }}
    >
      {accent && <div className="w-[4px] shrink-0 bg-[#CC1100]" />}
      {children}
    </div>
  )
}

function TopBar({
  center,
  showFilters,
  activeFilterCount,
  onToggleFilters,
}: {
  center: React.ReactNode
  showFilters: boolean
  activeFilterCount: number
  onToggleFilters: () => void
}) {
  return (
    <div
      className="flex shrink-0 items-stretch border-b-2 border-[#111111] bg-[#F0EDE6]"
      style={{ height: TOP_BAR_HEIGHT }}
    >
      <Link
        to="/"
        className="font-display flex shrink-0 items-center border-r-2 border-[#111111] px-4 text-[16px] font-[800] tracking-[-0.01em] text-[#111111] uppercase transition-colors hover:bg-[#111111] hover:text-[#F0EDE6] sm:px-5 sm:text-[18px]"
      >
        <span className="truncate">Oracle Tutor</span>
      </Link>

      <div className="flex min-w-0 flex-1 self-stretch">{center}</div>

      <button
        onClick={onToggleFilters}
        className="font-display flex shrink-0 items-center gap-1.5 border-l-2 border-[#111111] px-3 text-[10px] font-[700] tracking-[0.12em] uppercase transition-colors sm:gap-2 sm:px-5 sm:text-[12px]"
        style={
          showFilters || activeFilterCount > 0
            ? { background: '#111111', color: '#F0EDE6' }
            : { color: '#111111' }
        }
      >
        <FunnelIcon
          weight={activeFilterCount > 0 ? 'fill' : 'regular'}
          className="h-3.5 w-3.5"
        />
        Filters
        {activeFilterCount > 0 && (
          <span className="font-display flex h-4 w-4 items-center justify-center bg-[#CC1100] text-[9px] font-bold text-white">
            {activeFilterCount}
          </span>
        )}
      </button>
    </div>
  )
}

function FilterStrip({
  filters,
  onFilterChange,
  onHeightChange,
}: {
  filters: FilterState
  onFilterChange: (f: FilterState) => void
  onHeightChange: (height: number) => void
}) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const node = ref.current
    if (!node) return

    const updateHeight = () => onHeightChange(node.getBoundingClientRect().height)
    updateHeight()

    const observer = new ResizeObserver(updateHeight)
    observer.observe(node)

    return () => observer.disconnect()
  }, [onHeightChange])

  return (
    <div
      ref={ref}
      className="z-30 flex shrink-0 items-center border-b-2 border-[#111111] bg-white px-3 sm:px-4"
    >
      <FilterBar
        filters={filters}
        onFilterChange={onFilterChange}
        variant="inline"
      />
    </div>
  )
}

// ── Route entry point ─────────────────────────────────────────────────────────

export default function SearchPage() {
  const { id } = useParams<{ id?: string }>()
  const [searchParams] = useSearchParams()
  const query = searchParams.get('q') ?? ''

  if (id) return <CardMode id={id} />
  return <SearchMode query={query} />
}
