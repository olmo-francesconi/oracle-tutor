import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { CardImage } from './CardImage'
import { FilterBar } from './FilterBar'
import { getCardImageUrl } from '../utils'
import type { SimilarCard, FilterState } from '../types'
import { cn } from '../lib/cn'

const BOUNCE_DELAYS = ['0s', '0.2s', '0.4s'] as const

function getSectionKey(
  similarity: number
): 'perfect' | 'great' | 'good' | 'poor' | 'default' {
  if (similarity >= 0.999) return 'perfect'
  if (similarity >= 0.8) return 'great'
  if (similarity >= 0.6) return 'good'
  if (similarity >= 0.4) return 'poor'
  return 'default'
}

const SECTION_LABELS: Record<string, string> = {
  perfect: 'Perfect',
  great: 'Great',
  good: 'Good',
  poor: 'Poor',
  default: 'Other',
}

const SECTION_COLORS: Record<string, string> = {
  perfect: 'bg-[#111111]',
  great: 'bg-[#444444]',
  good: 'bg-[#888888]',
  poor: 'bg-[#BBBBBB]',
  default: 'bg-[#DDDDDD]',
}

const CARD_RADIUS_STYLE = { borderRadius: '4.5% / 3.21%' } as const

function AnimatedCount({ value }: { value: number }) {
  const [display, setDisplay] = useState(value)
  const prevRef = useRef(value)
  const rafRef = useRef<ReturnType<typeof requestAnimationFrame> | null>(null)

  useEffect(() => {
    const target = value
    const start = prevRef.current

    if (target <= start) {
      prevRef.current = target
      queueMicrotask(() => setDisplay(target))
      return
    }

    prevRef.current = target
    const duration = 350
    const startTime = performance.now()

    const tick = (now: number) => {
      const elapsed = now - startTime
      const t = Math.min(elapsed / duration, 1)
      const eased = 1 - (1 - t) ** 2
      setDisplay(Math.round(start + (target - start) * eased))
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick)
      }
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [value])

  return <>{display.toLocaleString()}</>
}

interface CardGridProps {
  cards: SimilarCard[]
  isLoading: boolean
  isFetchingNextPage: boolean
  hasNextPage: boolean
  fetchNextPage: () => void
  onCardClick: (card: SimilarCard) => void
  selectedCardId?: string | null
  noResultsMessage?: React.ReactNode
  searchQuery?: string
  filters?: FilterState
  onFilterChange?: (filters: FilterState) => void
  header?: React.ReactNode
  showFloatingFilters?: boolean
}

const CardGridItem = memo(function CardGridItem({
  card,
  isSelected,
  onCardClick,
}: {
  card: SimilarCard
  isSelected: boolean
  onCardClick: (card: SimilarCard) => void
}) {
  const handleClick = useCallback(() => onCardClick(card), [card, onCardClick])

  return (
    <div
      onClick={handleClick}
      className={cn(
        'group flex cursor-pointer flex-col overflow-hidden border-2 transition-colors',
        isSelected ? 'border-[#CC1100]' : 'border-[#111111] hover:border-[#CC1100]'
      )}
    >
      {/* Similarity score bar */}
      {card.similarity !== undefined && (
        <div
          className={cn(
            'flex justify-end border-b-2 bg-[#F0EDE6] px-2 py-1 transition-colors',
            isSelected ? 'border-[#CC1100]' : 'border-[#111111]'
          )}
        >
          <span className="font-display tabular-nums text-[10px] font-bold leading-tight tracking-[0.06em] text-[#111111]">
            {(card.similarity * 100).toFixed(0)}%
          </span>
        </div>
      )}

      {/* Image area: dark background reveals card's natural corner radius */}
      <div className="relative aspect-[5/7] overflow-hidden bg-[#111111]">
        <CardImage
          src={getCardImageUrl(card, 'normal')}
          srcSet={`${getCardImageUrl(card, 'normal')} 1x, ${getCardImageUrl(card, 'large')} 2x`}
          sizes="(min-width: 768px) 240px, 45vw"
          alt={card.name}
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover"
          style={CARD_RADIUS_STYLE}
        />
      </div>
    </div>
  )
})

export function CardGrid({
  cards,
  isLoading,
  isFetchingNextPage,
  hasNextPage,
  fetchNextPage,
  onCardClick,
  selectedCardId,
  noResultsMessage,
  searchQuery,
  filters,
  onFilterChange,
  header,
  showFloatingFilters = true,
}: CardGridProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)

  // Scroll to top when search query changes
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({ top: 0, behavior: 'instant' })
    }
  }, [searchQuery])

  // Infinite scroll: fetch next page when sentinel enters view
  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || !hasNextPage || isFetchingNextPage) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) fetchNextPage()
      },
      { root: scrollContainerRef.current, rootMargin: '200px' }
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  // Group cards by similarity section
  const sections = (['perfect', 'great', 'good', 'poor', 'default'] as const).map((key) => ({
    key,
    cards: cards.filter((c) => getSectionKey(c.similarity ?? 0) === key),
  })).filter((s) => s.cards.length > 0)

  if (isLoading && cards.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2 text-[#7A7670]">
          {BOUNCE_DELAYS.map((d) => (
            <div
              key={d}
              className="h-2 w-2 animate-bounce rounded-full bg-[#111111]"
              style={{ animationDelay: d }}
            />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div ref={scrollContainerRef} className="h-full flex-1 overflow-y-auto bg-transparent">
      {header}

      {showFloatingFilters && filters && onFilterChange && (
        <div className="sticky top-0 z-40 -mb-2 hidden border-b-2 border-[#111111] bg-[#F0EDE6] py-3 pr-4 md:block">
          <FilterBar filters={filters} onFilterChange={onFilterChange} variant="inline" />
        </div>
      )}

      {!isLoading && cards.length === 0 && (
        <div className="p-4">{noResultsMessage}</div>
      )}

      {cards.length > 0 && (
        <div className="p-4 pb-10 md:p-6">
          {sections.map(({ key, cards: sectionCards }) => (
            <div key={key} className="mb-8">
              {/* Section header */}
              <div className="mb-4 flex items-center gap-3 border-b-2 border-[#111111] pb-3">
                <span className="font-display text-[13px] font-bold uppercase tracking-[0.14em] text-[#111111]">
                  {SECTION_LABELS[key]}
                </span>
                <span className="text-[11px] text-[#7A7670]">
                  <AnimatedCount value={sectionCards.length} />
                </span>
                <div className={cn('h-[2px] flex-1', SECTION_COLORS[key])} />
              </div>

              {/* Card grid */}
              <div
                className="grid gap-3 md:gap-4"
                style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}
              >
                {sectionCards.map((card) => (
                  <CardGridItem
                    key={`${card.oracle_id}:${card.face_ix}`}
                    card={card}
                    isSelected={selectedCardId === `${card.oracle_id}:${card.face_ix}`}
                    onCardClick={onCardClick}
                  />
                ))}
              </div>
            </div>
          ))}

          {/* Infinite scroll sentinel */}
          <div ref={sentinelRef} />

          {isFetchingNextPage && (
            <div className="flex justify-center py-6">
              <div className="flex gap-2 text-[#7A7670]">
                {BOUNCE_DELAYS.map((d) => (
                  <div
                    key={d}
                    className="h-2 w-2 animate-bounce rounded-full bg-[#111111]"
                    style={{ animationDelay: d }}
                  />
                ))}
              </div>
            </div>
          )}

          {!hasNextPage && !isFetchingNextPage && (
            <div className="flex flex-col items-center gap-1 pb-6 pt-2">
              <span className="font-display text-[11px] uppercase tracking-[0.12em] text-[#7A7670]">
                {cards.length >= 1000 ? 'Showing the best 1,000 cards' : 'End of results'}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
