import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { useVirtualizer } from '@tanstack/react-virtual'
import { CardImage } from './CardImage'
import { FilterBar } from './FilterBar'
import { getCardImageUrl } from '../utils'
import type { SimilarCard, FilterState } from '../types'
import { cn } from '../lib/cn'

const BOUNCE_DELAYS = ['0s', '0.2s', '0.4s'] as const
const CARD_RADIUS_STYLE = { borderRadius: '4.5% / 3.21%' } as const
const MIN_CARD_WIDTH_PX = 240
const ASPECT_H_OVER_W = 7 / 5
const LOADER_ROW_HEIGHT_PX = 96

interface CardGridProps {
  cards: SimilarCard[]
  isLoading: boolean
  isFetchingNextPage: boolean
  hasNextPage: boolean
  fetchNextPage: () => void
  onCardClick: (card: SimilarCard) => void
  noResultsMessage?: React.ReactNode
  searchQuery?: string
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
      <div className="absolute top-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full border border-white/5 bg-[#171717]/90 px-3 py-1 shadow-lg backdrop-blur-md">
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
  filters,
  onFilterChange,
  header,
  showFloatingFilters = true,
}: CardGridProps) {
  const [isAnimating, setIsAnimating] = useState(false)

  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const [viewportWidth, setViewportWidth] = useState(0)

  // Scroll to top when search query changes
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [searchQuery])

  // Release the "pagination lock" when the request finishes (avoid per-card animation callbacks).
  useEffect(() => {
    if (!isFetchingNextPage) setIsAnimating(false)
  }, [isFetchingNextPage])

  const startNextPageFetch = useCallback(() => {
    if (isAnimating) return
    if (!hasNextPage) return
    if (isFetchingNextPage) return
    setIsAnimating(true)
    fetchNextPage()
  }, [fetchNextPage, hasNextPage, isAnimating, isFetchingNextPage])

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

  const rows = useMemo(() => {
    const count = layout.columns > 0 ? Math.ceil(cards.length / layout.columns) : 0
    const hasLoader = hasNextPage
    return {
      itemRows: count,
      totalRows: count + (hasLoader ? 1 : 0),
      hasLoader,
    }
  }, [cards.length, hasNextPage, layout.columns])

  const rowVirtualizer = useVirtualizer({
    count: rows.totalRows,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: (index) => {
      if (rows.hasLoader && index === rows.totalRows - 1) return LOADER_ROW_HEIGHT_PX
      return layout.rowPitch
    },
    overscan: 6,
  })

  const virtualRows = rowVirtualizer.getVirtualItems()

  // Trigger infinite pagination as we approach the end of the virtualized content.
  useEffect(() => {
    if (!rows.hasLoader) return
    const last = virtualRows[virtualRows.length - 1]
    if (!last) return
    if (last.index >= rows.totalRows - 1) {
      startNextPageFetch()
    }
  }, [rows.hasLoader, rows.totalRows, startNextPageFetch, virtualRows])

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
          {/* Floating Filter Button */}
          {showFloatingFilters && filters && onFilterChange && (
            <div className="fixed top-6 right-8 z-40 hidden md:block">
              <FilterBar filters={filters} onFilterChange={onFilterChange} />
            </div>
          )}

          {/* Virtualized grid */}
          <div
            style={{
              padding: layout.padding,
              paddingBottom: layout.paddingBottom,
            }}
          >
            <div
              style={{
                height: rowVirtualizer.getTotalSize(),
                position: 'relative',
                width: '100%',
              }}
            >
              {virtualRows.map((vRow) => {
                const isLoaderRow =
                  rows.hasLoader && vRow.index === rows.totalRows - 1

                if (isLoaderRow) {
                  return (
                    <div
                      key={vRow.key}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: vRow.size,
                        transform: `translateY(${vRow.start}px)`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        paddingTop: 24,
                        paddingBottom: 24,
                      }}
                    >
                      {isFetchingNextPage ? (
                        <div className="flex items-center gap-2 text-[#737373]">
                          {BOUNCE_DELAYS.map((d) => (
                            <div
                              key={d}
                              className="h-2 w-2 animate-bounce rounded-full bg-[#e3dccb]"
                              style={{ animationDelay: d }}
                            />
                          ))}
                        </div>
                      ) : null}
                    </div>
                  )
                }

                const start = vRow.index * layout.columns
                const rowCards = cards.slice(start, start + layout.columns)

                return (
                  <div
                    key={vRow.key}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: vRow.size,
                      transform: `translateY(${vRow.start}px)`,
                      paddingBottom: layout.gap,
                      boxSizing: 'border-box',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        gap: layout.gap,
                        height: layout.cardHeight,
                      }}
                    >
                      {rowCards.map((card, colIdx) => {
                        const index = start + colIdx
                        // With virtualization, mount/unmount happens during scroll; avoid re-running entry animations.
                        const effectiveAnimateIn = false

                        return (
                          <div
                            key={card.id}
                            style={{ width: layout.cardWidth, flex: '0 0 auto' }}
                          >
                            <CardGridItem
                              card={card}
                              index={index}
                              animateIn={effectiveAnimateIn}
                              onCardClick={onCardClick}
                            />
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>

            {!isLoading && cards.length === 0 && noResultsMessage}
            {!hasNextPage && cards.length > 0 && (
              <div className="flex justify-center pt-8 pb-6">
                <span className="text-sm text-[#525252]">End of results</span>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
