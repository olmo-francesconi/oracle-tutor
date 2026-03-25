import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Helmet } from 'react-helmet-async'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { FunnelIcon } from '@phosphor-icons/react'
import { getCard, getSimilarCards, searchOracleText } from '../api'
import { CardGrid } from '../components/CardGrid'
import { CardOverlay } from '../components/CardOverlay'
import { FilterBar } from '../components/FilterBar'
import { PageSEO } from '../components/PageSEO'
import { SymbolText } from '../components/SymbolText'
import { UnifiedSearchBox } from '../components/UnifiedSearchBox'
import { getBaseUrl } from '../lib/seo'
import type { FilterState, SimilarCard } from '../types'
import { getCardImageUrl, getImageSideForFace } from '../utils'

// ── Search mode ──────────────────────────────────────────────────────────────

function SearchMode({ query }: { query: string }) {
  const [selectedCard, setSelectedCard] = useState<SimilarCard | null>(null)
  const [filters, setFilters] = useState<FilterState>({})
  const [showFilters, setShowFilters] = useState(false)

  const { data: cards = [], isLoading } = useQuery({
    queryKey: ['oracle-search', query, filters],
    queryFn: () => searchOracleText(query, 0, 60, filters),
    enabled: !!query,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
  })

  const currentIndex =
    selectedCard != null
      ? cards.findIndex(
          (c) =>
            c.oracle_id === selectedCard.oracle_id &&
            c.face_ix === selectedCard.face_ix
        )
      : -1

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedCard(null)
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [])

  const activeFilterCount = Object.keys(filters).filter(
    (k) => filters[k as keyof FilterState] !== undefined
  ).length

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

      {selectedCard && (
        <CardOverlay
          card={selectedCard}
          onClose={() => setSelectedCard(null)}
          hasPrev={currentIndex > 0}
          hasNext={currentIndex >= 0 && currentIndex < cards.length - 1}
          onPrev={() => setSelectedCard(cards[currentIndex - 1])}
          onNext={() => setSelectedCard(cards[currentIndex + 1])}
        />
      )}

      <div className="flex h-screen flex-col overflow-hidden bg-[#F0EDE6]">
        <TopBar
          center={
            <UnifiedSearchBox
              key={query}
              size="topBar"
              initialValue={query}
              className="h-full w-full"
            />
          }
          showFilters={showFilters}
          activeFilterCount={activeFilterCount}
          onToggleFilters={() => setShowFilters((v) => !v)}
        />

        {showFilters && (
          <FilterStrip filters={filters} onFilterChange={setFilters} />
        )}

        {query && (
          <DetailBand accent>
            <div className="flex items-baseline gap-3 px-6 py-3.5">
              <h2 className="font-display text-[20px] leading-none font-[900] tracking-[-0.02em] text-[#111111] uppercase">
                {query}
              </h2>
              {!isLoading && (
                <span className="font-mono text-[11px] text-[#7A7670]">
                  {cards.length} results
                </span>
              )}
            </div>
          </DetailBand>
        )}

        <div className="min-h-0 flex-1">
          <CardGrid
            cards={cards}
            isLoading={isLoading}
            isFetchingNextPage={false}
            hasNextPage={false}
            fetchNextPage={() => {}}
            onCardClick={setSelectedCard}
            selectedCardId={selectedCard ? `${selectedCard.oracle_id}:${selectedCard.face_ix}` : null}
            noResultsMessage={
              <div className="px-8 py-16 text-center">
                <p className="font-display text-xl font-bold tracking-wide text-[#7A7670] uppercase">
                  No results
                </p>
                <p className="mt-2 font-mono text-[11px] text-[#7A7670]">
                  Try adjusting your search terms
                </p>
              </div>
            }
            searchQuery={query}
            showFloatingFilters={false}
          />
        </div>
      </div>
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
      getSimilarCards(id, selectedFaceIx, pageParam, 60, filters),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length === 60 ? allPages.length * 60 : undefined,
    enabled: !!id,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
  })

  const similarCards = useMemo(
    () => similarData?.pages.flatMap((page) => page) ?? [],
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

  const currentIndex =
    selectedCard != null
      ? navigableCards.findIndex(
          (c) =>
            c.oracle_id === selectedCard.oracle_id &&
            c.face_ix === selectedCard.face_ix
        )
      : -1

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null)
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [])

  useEffect(() => {
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
    currentIndex,
    navigableCards.length,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  ])

  const activeFilterCount = Object.keys(filters).filter(
    (k) => filters[k as keyof FilterState] !== undefined
  ).length

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
    <div className="flex h-[100dvh] w-full flex-col overflow-hidden bg-[#F0EDE6]">
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

      {selectedCard && (
        <CardOverlay
          card={selectedCard}
          onClose={() => setSelected(null)}
          hasPrev={currentIndex > 0}
          hasNext={
            currentIndex >= 0 && currentIndex < navigableCards.length - 1
          }
          onPrev={() =>
            setSelected({ routeId: id, card: navigableCards[currentIndex - 1] })
          }
          onNext={() =>
            setSelected({ routeId: id, card: navigableCards[currentIndex + 1] })
          }
        />
      )}

      <TopBar
        center={
          <UnifiedSearchBox
            key={displayName}
            size="topBar"
            initialValue={displayName}
            className="h-full w-full"
          />
        }
        showFilters={showFilters}
        activeFilterCount={activeFilterCount}
        onToggleFilters={() => setShowFilters((v) => !v)}
      />

      {showFilters && (
        <FilterStrip filters={filters} onFilterChange={setFilters} />
      )}

      <DetailBand accent>
        <div className="flex min-w-0 flex-1 items-center gap-3 px-6 py-3.5">
          <h1 className="font-display shrink-0 text-[20px] leading-none font-[900] tracking-[-0.02em] text-[#111111] uppercase">
            {displayName}
          </h1>
          {displayType && (
            <>
              <span className="shrink-0 text-[#CCCCCC]" aria-hidden>·</span>
              <span className="font-mono shrink-0 text-[11px] text-[#7A7670]">{displayType}</span>
            </>
          )}
          {displayMana && (
            <>
              <span className="shrink-0 text-[#CCCCCC]" aria-hidden>·</span>
              <span className="font-mono shrink-0 text-[11px] text-[#7A7670]">
                <SymbolText text={displayMana} />
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
          className="font-mono flex shrink-0 items-center border-l-2 border-[#111111] px-5 text-[11px] uppercase tracking-[0.08em] text-[#7A7670] transition-colors hover:bg-[#111111] hover:text-[#F0EDE6]"
        >
          View card ↗
        </button>
      </DetailBand>

      <div className="min-h-0 flex-1">
        <CardGrid
          cards={similarCards}
          isLoading={similarLoading}
          isFetchingNextPage={isFetchingNextPage}
          hasNextPage={!!hasNextPage}
          fetchNextPage={fetchNextPage}
          onCardClick={(c) => setSelected({ routeId: id, card: c })}
          selectedCardId={selectedCard ? `${selectedCard.oracle_id}:${selectedCard.face_ix}` : null}
          searchQuery={id}
          filters={filters}
          onFilterChange={setFilters}
          showFloatingFilters={false}
        />
      </div>
    </div>
  )
}

// ── Shared chrome ─────────────────────────────────────────────────────────────

function DetailBand({ accent, children }: { accent?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex shrink-0 items-stretch border-b-2 border-[#111111] bg-[#F0EDE6]">
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
      className="flex shrink-0 items-stretch border-b-2 border-[#111111]"
      style={{ height: 56 }}
    >
      <Link
        to="/"
        className="font-display flex shrink-0 items-center border-r-2 border-[#111111] px-5 text-[18px] font-[800] tracking-[-0.01em] text-[#111111] uppercase transition-colors hover:bg-[#111111] hover:text-[#F0EDE6]"
      >
        Oracle Tutor
      </Link>

      <div className="flex min-w-0 flex-1 self-stretch">{center}</div>

      <button
        onClick={onToggleFilters}
        className="font-display flex shrink-0 items-center gap-2 border-l-2 border-[#111111] px-5 text-[12px] font-[700] tracking-[0.12em] uppercase transition-colors"
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
}: {
  filters: FilterState
  onFilterChange: (f: FilterState) => void
}) {
  return (
    <div className="flex shrink-0 items-center border-b-2 border-[#111111] bg-white px-4">
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
