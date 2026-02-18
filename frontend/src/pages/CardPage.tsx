import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { ArrowLeft } from '@phosphor-icons/react'
import { useEffect, useMemo, useState } from 'react'
import { Helmet } from 'react-helmet-async'
import { Link, useParams } from 'react-router-dom'
import { getCard, getSimilarCards } from '../api'
import { CardGrid } from '../components/CardGrid'
import { CardImage } from '../components/CardImage'
import { CardOverlay } from '../components/CardOverlay'
import { DeveloperLinks } from '../components/DeveloperLinks'
import { MobileDrawer } from '../components/MobileDrawer'
import { MobileResultsHeader } from '../components/MobileResultsHeader'
import { MobileBottomBar } from '../components/MobileBottomBar'
import { PageSEO } from '../components/PageSEO'
import { SymbolText } from '../components/SymbolText'
import type { FilterState, SimilarCard } from '../types'
import { getCardImageUrl } from '../utils'

export function CardPage() {
  const { id } = useParams<{ id: string }>()
  const [selected, setSelected] = useState<{
    routeId: string
    card: SimilarCard
  } | null>(null)
  const selectedCard = selected?.routeId === (id ?? '') ? selected.card : null
  const [filters, setFilters] = useState<FilterState>({})
  const [isDetailsOpen, setIsDetailsOpen] = useState(false)

  const {
    data: card,
    isLoading: cardLoading,
    error: cardError,
  } = useQuery({
    queryKey: ['card', id],
    queryFn: () => getCard(id!),
    enabled: !!id,
  })

  const {
    data: similarData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: similarLoading,
  } = useInfiniteQuery({
    queryKey: ['similar', id, filters],
    queryFn: ({ pageParam = 0 }) => {
      return getSimilarCards(id!, pageParam, 60, filters)
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      // If we received fewer items than the limit (60), we're at the end
      return lastPage.length === 60 ? allPages.length * 60 : undefined
    },
    enabled: !!id,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
  })

  const similarCards = useMemo(() => {
    return similarData?.pages.flatMap((page) => page) || []
  }, [similarData])

  const navigableCards = useMemo(() => {
    if (!card) return similarCards
    const mainAsSimilar = { ...card, similarity: 1 } as SimilarCard
    return [mainAsSimilar, ...similarCards]
  }, [card, similarCards])

  const currentIndex =
    selectedCard != null
      ? navigableCards.findIndex((c) => c.id === selectedCard.id)
      : -1

  const hasPrev = currentIndex > 0
  const hasNext =
    currentIndex >= 0 && currentIndex < navigableCards.length - 1

  // Handle keyboard ESC to close overlay
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null)
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [])

  // Prefetch next page when viewing a card near the end of loaded results
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

  if (cardLoading)
    return (
      <div className="flex h-screen items-center justify-center text-[#f5f2eb]">
        Loading knowledge...
      </div>
    )
  if (cardError || !card)
    return (
      <div className="flex h-screen items-center justify-center text-[#f5f2eb]">
        Card not found.
      </div>
    )

  // Resolve display properties for the main card
  // If the card has faces (DFC), prefer the first face for the main view if flattened props are missing
  const displayType = card.type_line || card.faces?.[0]?.type_line
  const displayMana = card.mana_cost || card.faces?.[0]?.mana_cost
  const displayOracle = card.oracle_text || card.faces?.[0]?.oracle_text

  // Main card image usually defaults to front face
  const mainCardImageUrl = getCardImageUrl(card)
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
    name: card.name,
    description:
      truncatedDescription || `${card.name} — Magic: The Gathering card.`,
    image: mainCardImageUrl,
  }

  return (
    <div className="flex h-[100dvh] w-full flex-col overflow-hidden bg-transparent md:h-screen md:flex-row">
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
      {/* Overlay Component */}
      {selectedCard && (
        <CardOverlay
          card={selectedCard}
          onClose={() => setSelected(null)}
          hasPrev={hasPrev}
          hasNext={hasNext}
          onPrev={() =>
            setSelected({
              routeId: id ?? '',
              card: navigableCards[currentIndex - 1],
            })
          }
          onNext={() =>
            setSelected({
              routeId: id ?? '',
              card: navigableCards[currentIndex + 1],
            })
          }
        />
      )}

      {/* Mobile Drawer - Card Details */}
      <MobileDrawer
        isOpen={isDetailsOpen}
        title="Details"
        onClose={() => setIsDetailsOpen(false)}
      >
        {/* Card "Paper" Container */}
        <div className="rounded-xl border border-[#e5e5e5] bg-white p-4 text-[#1c1c1c] shadow-lg">
          {/* Compact top row: full card (no crop) + key stats */}
          <div className="flex gap-4">
            <button
              type="button"
              className="relative aspect-[5/7] w-[42%] max-w-[180px] shrink-0 overflow-hidden bg-[#f0f0f0] shadow-lg ring-1 ring-black/5"
              style={{ borderRadius: '4.5% / 3.21%' }}
              onClick={() => {
                setSelected({
                  routeId: id ?? '',
                  card: { ...card, similarity: 1 } as SimilarCard,
                })
                setIsDetailsOpen(false)
              }}
              aria-label="Open large card view"
            >
              <CardImage
                src={mainCardImageUrl}
                alt={card.name}
                className="h-full w-full object-contain"
              />
            </button>

            <div className="min-w-0 flex-1">
              <h2 className="text-xl leading-tight font-bold text-[#1c1c1c]">
                {card.name}
              </h2>

              <p className="mt-2 text-sm leading-snug font-medium text-[#404040]">
                <span className="text-[#1c1c1c]">{displayType || '—'}</span>{' '}
                <span className="px-1.5 text-[#a3a3a3]" aria-hidden="true">
                  •
                </span>
                <span className="text-[#1c1c1c]">
                  <SymbolText text={displayMana || 'None'} />
                </span>
              </p>
            </div>
          </div>

          <div className="mt-4 border-t border-[#e5e5e5] pt-4">
            <span className="mb-2 block text-[11px] font-semibold tracking-wider text-[#737373] uppercase">
              Oracle Text
            </span>
            <p className="text-[13px] leading-snug whitespace-pre-wrap text-[#404040]">
              <SymbolText text={displayOracle} />
            </p>
          </div>
        </div>
      </MobileDrawer>

      {/* Sidebar - Selected Card Details */}
      <div className="hidden h-full w-full flex-shrink-0 flex-col overflow-y-auto border-r border-[#e5e5e5] bg-[#f5f2eb] p-5 md:flex md:w-[380px]">
        <Link
          to="/"
          className="mb-6 flex items-center gap-2 text-[#525252] transition-colors hover:text-[#1c1c1c]"
        >
          <ArrowLeft className="h-4 w-4" /> Back to Search
        </Link>

        {/* Card "Paper" Container */}
        <div className="rounded-xl border border-[#e5e5e5] bg-white p-5 text-[#1c1c1c] shadow-lg">
          {/* Card Image - Clickable to open overlay */}
          <div
            className="relative mb-5 aspect-[5/7] w-full cursor-pointer overflow-hidden bg-[#f0f0f0] shadow-lg ring-1 ring-black/5 transition-all hover:scale-[1.02] hover:ring-black/10"
            style={{ borderRadius: '4.5% / 3.21%' }}
            onClick={() =>
              setSelected({
                routeId: id ?? '',
                card: { ...card, similarity: 1 } as SimilarCard,
              })
            }
          >
            <CardImage
              src={mainCardImageUrl}
              alt={card.name}
              className="h-full w-full object-cover"
            />
          </div>

          <h1 className="mb-2 text-2xl leading-tight font-bold text-[#1c1c1c]">
            {card.name}
          </h1>

          <div className="mb-4">
            <p className="text-sm leading-snug font-medium text-[#404040]">
              <span className="text-[#1c1c1c]">{displayType || '—'}</span>{' '}
              <span className="px-1.5 text-[#a3a3a3]" aria-hidden="true">
                •
              </span>
              <span className="text-[#1c1c1c]">
                <SymbolText text={displayMana || 'None'} />
              </span>
            </p>
          </div>

          <div className="border-t border-[#e5e5e5] pt-4">
            <span className="mb-2 block text-xs font-semibold tracking-wider text-[#737373] uppercase">
              Oracle Text
            </span>
            <p className="text-sm leading-relaxed whitespace-pre-wrap text-[#404040]">
              <SymbolText text={displayOracle} />
            </p>
          </div>
        </div>

        <div className="mt-auto flex items-end justify-between gap-6 pt-6">
          <DeveloperLinks variant="dark" />
        </div>
      </div>

      {/* Main Content - Similar Cards Grid */}
      <CardGrid
        header={
          <MobileResultsHeader
            backTo="/"
            title={card.name}
            titleVariant="card"
            drawerLabel="Details"
            onOpenDrawer={() => setIsDetailsOpen(true)}
            filters={filters}
            onFilterChange={setFilters}
          />
        }
        cards={similarCards}
        isLoading={similarLoading}
        isFetchingNextPage={isFetchingNextPage}
        hasNextPage={!!hasNextPage}
        fetchNextPage={fetchNextPage}
        onCardClick={(c) => setSelected({ routeId: id ?? '', card: c })}
        queryKey={id}
        filters={filters}
        onFilterChange={setFilters}
      />

      <MobileBottomBar />
    </div>
  )
}
