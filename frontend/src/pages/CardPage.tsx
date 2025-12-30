import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { ArrowLeft } from '@phosphor-icons/react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getCard, getSimilarCards } from '../api'
import { CardGrid } from '../components/CardGrid'
import { CardImage } from '../components/CardImage'
import { CardOverlay } from '../components/CardOverlay'
import { DeveloperLinks } from '../components/DeveloperLinks'
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

  // Update document title when card is loaded
  useEffect(() => {
    if (card?.name) {
      document.title = `${card.name} - Oracle tutor`
    }
  }, [card])

  // Handle keyboard ESC to close overlay
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null)
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [])

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

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-transparent md:flex-row">
      {/* Overlay Component */}
      {selectedCard && (
        <CardOverlay card={selectedCard} onClose={() => setSelected(null)} />
      )}

      {/* Sidebar - Selected Card Details */}
      <div className="flex h-full w-full flex-shrink-0 flex-col overflow-y-auto border-r border-[#e5e5e5] bg-[#f5f2eb] p-5 md:w-[380px]">
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

          <div className="mb-4 flex flex-col gap-3">
            <div className="flex flex-col">
              <span className="text-xs font-semibold tracking-wider text-[#737373] uppercase">
                Type
              </span>
              <span className="font-medium">{displayType}</span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col">
                <span className="text-xs font-semibold tracking-wider text-[#737373] uppercase">
                  Mana
                </span>
                <span className="font-medium">{displayMana || 'None'}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-xs font-semibold tracking-wider text-[#737373] uppercase">
                  Rank
                </span>
                <span className="font-medium">#{card.edhrec_rank}</span>
              </div>
            </div>
          </div>

          <div className="border-t border-[#e5e5e5] pt-4">
            <span className="mb-2 block text-xs font-semibold tracking-wider text-[#737373] uppercase">
              Oracle Text
            </span>
            <p className="text-sm leading-relaxed whitespace-pre-wrap text-[#404040]">
              {displayOracle}
            </p>
          </div>
        </div>

        <div className="mt-auto pt-6">
          <DeveloperLinks variant="dark" />
        </div>
      </div>

      {/* Main Content - Similar Cards Grid */}
      <CardGrid
        cards={similarCards}
        isLoading={similarLoading}
        isFetchingNextPage={isFetchingNextPage}
        hasNextPage={!!hasNextPage}
        fetchNextPage={fetchNextPage}
        onCardClick={(c) => setSelected({ routeId: id ?? '', card: c })}
        filters={filters}
        onFilterChange={setFilters}
      />
    </div>
  )
}
