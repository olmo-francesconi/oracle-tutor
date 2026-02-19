import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CaretDown } from '@phosphor-icons/react'
import { motion } from 'framer-motion'
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

const SECTION_SCORES: Record<string, string> = {
  perfect: '100%',
  great: '80-100%',
  good: '60-80%',
  poor: '40-60%',
  default: '<40%',
}

const SECTION_COLORS: Record<string, string> = {
  perfect: 'bg-blue-500',
  great: 'bg-emerald-500',
  good: 'bg-amber-500',
  poor: 'bg-red-500',
  default: 'bg-[#737373]',
}
const CARD_RADIUS_STYLE = { borderRadius: '4.5% / 3.21%' } as const
const MIN_CARD_WIDTH_PX = 240
const ASPECT_H_OVER_W = 7 / 5

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
  noResultsMessage?: React.ReactNode
  searchQuery?: string
  /** When this changes (e.g. card id or search query), we reset "Load" state for Other matches */
  queryKey?: string
  filters?: FilterState
  onFilterChange?: (filters: FilterState) => void
  header?: React.ReactNode
  showFloatingFilters?: boolean
}

const CardGridItem = memo(function CardGridItem({
  card,
  index,
  animateIn,
  onCardClick,
}: {
  card: SimilarCard
  index: number
  animateIn: boolean
  onCardClick: (card: SimilarCard) => void
}) {
  const delay = (index % 60) * 0.05
  const handleClick = useCallback(() => onCardClick(card), [card, onCardClick])

  const content = (
    <div
      onClick={handleClick}
      className="group relative block aspect-[5/7] cursor-pointer overflow-hidden border border-white/5 bg-[#262626] shadow-lg transition-all duration-300 hover:-translate-y-1 hover:scale-[1.02] hover:shadow-2xl hover:ring-1 hover:ring-[#e3dccb]/30"
      style={CARD_RADIUS_STYLE}
    >
      <CardImage
        src={getCardImageUrl(card, 'normal')}
        srcSet={`${getCardImageUrl(card, 'normal')} 1x, ${getCardImageUrl(card, 'large')} 2x`}
        sizes="(min-width: 768px) 240px, 45vw"
        alt={card.name}
        loading="lazy"
        decoding="async"
        className="h-full w-full object-cover"
      />

      {/* Similarity Badge */}
      <div className="absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-full border border-white/5 bg-[#171717]/90 px-3 py-1 shadow-lg backdrop-blur-md">
        <div
          className={cn(
            'h-2 w-2 rounded-full',
            card.similarity > 0.8
              ? 'bg-emerald-500/80 shadow-[0_0_8px_rgba(16,185,129,0.4)]'
              : 'bg-amber-500/80 shadow-[0_0_8px_rgba(245,158,11,0.4)]'
          )}
        />
        <span className="text-xs font-bold text-[#f5f2eb]">
          {(card.similarity * 100).toFixed(1)}%
        </span>
      </div>

      {/* Hover Name Overlay */}
      <div className="absolute inset-x-0 bottom-0 translate-y-full bg-gradient-to-t from-[#171717] via-[#171717]/90 to-transparent p-4 pt-12 transition-transform duration-300 group-hover:translate-y-0">
        <p className="truncate text-center text-sm font-medium text-[#f5f2eb]">
          {card.name}
        </p>
      </div>
    </div>
  )

  if (!animateIn) return content

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay, ease: 'easeOut' }}
    >
      {content}
    </motion.div>
  )
})

export function CardGrid({
  cards,
  isLoading,
  isFetchingNextPage,
  hasNextPage,
  fetchNextPage,
  onCardClick,
  noResultsMessage,
  searchQuery,
  queryKey,
  filters,
  onFilterChange,
  header,
  showFloatingFilters = true,
}: CardGridProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const [viewportWidth, setViewportWidth] = useState(0)

  const groupedCards = useMemo(() => {
    const groups: Record<string, SimilarCard[]> = {
      perfect: [],
      great: [],
      good: [],
      poor: [],
      default: [],
    }
    for (const card of cards) {
      const sim = card.similarity ?? 0
      const key = getSectionKey(sim)
      groups[key].push(card)
    }
    return [
      { key: 'perfect', cards: groups.perfect },
      { key: 'great', cards: groups.great },
      { key: 'good', cards: groups.good },
      { key: 'poor', cards: groups.poor },
      { key: 'default', cards: groups.default },
    ]
  }, [cards])

  const bestSectionKey = useMemo(() => {
    const first = groupedCards.find((g) => g.cards.length > 0)
    return first?.key ?? null
  }, [groupedCards])

  const initialCollapsedRef = useRef(false)
  const [collapsedSections, setCollapsedSections] = useState<
    Record<string, boolean>
  >({ default: true })

  useEffect(() => {
    if (!bestSectionKey || initialCollapsedRef.current) return
    initialCollapsedRef.current = true
    queueMicrotask(() => {
      setCollapsedSections((prev) => {
        const next = { ...prev }
        for (const { key } of groupedCards) {
          next[key] = key !== bestSectionKey
        }
        return next
      })
    })
  }, [bestSectionKey, groupedCards])

  const [userRequestedDefaultLoad, setUserRequestedDefaultLoad] = useState(false)

  const hasDefaultCards = useMemo(() => {
    return cards.some((c) => getSectionKey(c.similarity ?? 0) === 'default')
  }, [cards])

  const toggleSection = useCallback((key: string) => {
    setCollapsedSections((prev) => {
      const willExpand = prev[key] !== false
      if (willExpand && key === 'default') {
        setUserRequestedDefaultLoad(true)
      }
      return { ...prev, [key]: !prev[key] }
    })
  }, [])

  // Load perfect/great/good on page load; stop before default. Resume default only when user clicks Load
  useEffect(() => {
    if (isLoading || isFetchingNextPage || !hasNextPage) return
    if (cards.length >= 1000) return
    if (hasDefaultCards && !userRequestedDefaultLoad) return
    fetchNextPage()
  }, [
    isLoading,
    isFetchingNextPage,
    hasNextPage,
    cards.length,
    hasDefaultCards,
    userRequestedDefaultLoad,
    fetchNextPage,
  ])

  const searchOrQueryKey = queryKey ?? searchQuery
  useEffect(() => {
    queueMicrotask(() => setUserRequestedDefaultLoad(false))
  }, [searchOrQueryKey])

  // Scroll to top when search query changes
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [searchQuery])

  // Initial loading state is now handled inside the main return to preserve the scroll container ref
  const showInitialLoader = isLoading && cards.length === 0

  // Measure available width for responsive column calculation.
  useEffect(() => {
    const el = scrollContainerRef.current
    if (!el) return
    const update = () => setViewportWidth(el.clientWidth)
    update()

    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const layout = useMemo(() => {
    const w = viewportWidth || 0

    // Match the tailwind breakpoints used in the prior grid styles.
    const isSm = w >= 640
    const isMd = w >= 768

    const padding = isSm ? (isMd ? 16 : 24) : 12
    const paddingBottom = isMd ? 40 : 96
    const gap = isSm ? (isMd ? 16 : 20) : 12

    // Keep 2 columns on small screens for a stable layout.
    let columns = 2
    if (isMd) {
      const usable = Math.max(0, w - padding * 2)
      columns = Math.max(
        2,
        Math.floor((usable + gap) / (MIN_CARD_WIDTH_PX + gap))
      )
    }

    const usable = Math.max(1, w - padding * 2 - gap * (columns - 1))
    const cardWidth = usable / columns
    const cardHeight = cardWidth * ASPECT_H_OVER_W

    // Pitch includes the visual gap between rows.
    const rowPitch = cardHeight + gap

    return {
      padding,
      paddingBottom,
      gap,
      columns,
      cardWidth,
      cardHeight,
      rowPitch,
    }
  }, [viewportWidth])


  return (
    <div
      ref={scrollContainerRef}
      className="relative h-full flex-1 overflow-y-auto scroll-smooth bg-transparent"
    >
      {header}
      {showInitialLoader ? (
        <div className="flex h-full items-center justify-center">
          <div className="flex items-center gap-2 text-[#737373]">
            {BOUNCE_DELAYS.map((d) => (
              <div
                key={d}
                className="h-2 w-2 animate-bounce rounded-full bg-[#e3dccb]"
                style={{ animationDelay: d }}
              />
            ))}
          </div>
        </div>
      ) : (
        <>
          {/* Filter bar at top - above sections */}
          {showFloatingFilters && filters && onFilterChange && (
            <div
              className="sticky top-0 z-40 -mb-2 hidden border-b border-white/5 bg-[#1c1c1c]/60 pr-4 py-3 backdrop-blur-sm md:block"
              style={{ paddingRight: layout.padding }}
            >
              <FilterBar
                filters={filters}
                onFilterChange={onFilterChange}
                variant="inline"
              />
            </div>
          )}

          {/* Collapsible sections by match quality */}
          <div
            style={{
              padding: layout.padding,
              paddingBottom: layout.paddingBottom,
            }}
          >
            {groupedCards.map(({ key, cards: sectionCards }) => {
              const isCollapsed = collapsedSections[key]

              return (
                <div
                  key={key}
                  className={cn(
                    'transition-[margin] duration-200 ease-out',
                    isCollapsed ? 'mb-2' : 'mb-8'
                  )}
                >
                  <button
                    type="button"
                    onClick={() => toggleSection(key)}
                    className="mb-4 flex w-full items-center justify-between gap-3 rounded-lg border border-white/5 bg-white/5 px-4 py-3 text-left transition-colors duration-200 hover:bg-white/10"
                  >
                    <span className="flex items-center gap-2 font-semibold text-[#f5f2eb]">
                      <span
                        className={cn(
                          'h-2 w-2 shrink-0 rounded-full',
                          SECTION_COLORS[key]
                        )}
                        aria-hidden
                      />
                      {SECTION_LABELS[key]}
                      <span className="text-sm font-normal text-[#a3a3a3]">
                        {SECTION_SCORES[key]}
                      </span>
                      <span className="text-sm font-normal text-[#737373]">
                        {key === 'default' && !userRequestedDefaultLoad
                          ? '· Load'
                          : (
                            <>
                              · <AnimatedCount value={sectionCards.length} />
                            </>
                          )}
                      </span>
                    </span>
                    <CaretDown
                      className={cn(
                        'h-5 w-5 shrink-0 text-[#a3a3a3] transition-transform duration-200',
                        isCollapsed ? '-rotate-90' : ''
                      )}
                    />
                  </button>

                  <div
                    className="grid transition-[grid-template-rows_0.25s_ease-out]"
                    style={{
                      gridTemplateRows: isCollapsed ? '0fr' : '1fr',
                    }}
                  >
                    <div className="min-h-0 overflow-hidden">
                      <div
                        style={{
                          display: 'grid',
                          gridTemplateColumns: `repeat(${layout.columns}, minmax(0, 1fr))`,
                          gap: layout.gap,
                        }}
                      >
                        {sectionCards.map((card, index) => (
                        <div
                          key={card.id}
                          style={{
                            width: '100%',
                            aspectRatio: '5/7',
                          }}
                        >
                          <CardGridItem
                            card={card}
                            index={index}
                            animateIn={false}
                            onCardClick={onCardClick}
                          />
                        </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}

            {!isLoading && cards.length === 0 && noResultsMessage}

            {/* Loading indicator while fetching all cards */}
            {isFetchingNextPage && (
              <div className="flex justify-center py-6">
                <div className="flex gap-2 text-[#737373]">
                  {BOUNCE_DELAYS.map((d) => (
                    <div
                      key={d}
                      className="h-2 w-2 animate-bounce rounded-full bg-[#e3dccb]"
                      style={{ animationDelay: d }}
                    />
                  ))}
                </div>
              </div>
            )}

            {!hasNextPage && cards.length > 0 && !isFetchingNextPage && (
              <div className="flex flex-col items-center gap-1 pb-6">
                <span className="text-sm text-[#525252]">
                  {cards.length >= 1000
                    ? 'Showing the best 1,000 cards'
                    : 'End of results'}
                </span>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
