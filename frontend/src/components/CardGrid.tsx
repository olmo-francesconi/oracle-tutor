import { useEffect, useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { CardImage } from './CardImage'
import { FilterBar } from './FilterBar'
import { getCardImageUrl } from '../utils'
import type { SimilarCard, FilterState } from '../types'
import { cn } from '../lib/cn'

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
}

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
}: CardGridProps) {
  const [isAnimating, setIsAnimating] = useState(false)

  const [isLoaderInView, setIsLoaderInView] = useState(false)
  const scrollContainerRef = useRef<HTMLDivElement>(null)

  // Scroll to top when search query changes
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [searchQuery])

  const startNextPageFetch = () => {
    if (isAnimating) return
    if (!hasNextPage) return
    if (isFetchingNextPage) return
    setIsAnimating(true)
    fetchNextPage()
  }

  // Initial loading state is now handled inside the main return to preserve the scroll container ref
  const showInitialLoader = isLoading && cards.length === 0

  return (
    <div
      ref={scrollContainerRef}
      className="relative h-full flex-1 overflow-y-auto scroll-smooth bg-transparent"
    >
      {showInitialLoader ? (
        <div className="flex h-full items-center justify-center">
          <div className="flex items-center gap-2 text-[#737373]">
            <div
              className="h-2 w-2 animate-bounce rounded-full bg-[#e3dccb]"
              style={{ animationDelay: '0s' }}
            ></div>
            <div
              className="h-2 w-2 animate-bounce rounded-full bg-[#e3dccb]"
              style={{ animationDelay: '0.2s' }}
            ></div>
            <div
              className="h-2 w-2 animate-bounce rounded-full bg-[#e3dccb]"
              style={{ animationDelay: '0.4s' }}
            ></div>
          </div>
        </div>
      ) : (
        <>
          {/* Floating Filter Button */}
          {filters && onFilterChange && (
            <div className="fixed top-6 right-8 z-40">
              <FilterBar filters={filters} onFilterChange={onFilterChange} />
            </div>
          )}

          {/* Grid with larger cards (fewer columns) */}
          <div className="grid grid-cols-1 gap-6 p-6 pb-10 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {cards.map((s, index) => (
              <motion.div
                key={s.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  duration: 0.3,
                  delay: (index % 60) * 0.05,
                  ease: 'easeOut',
                }}
                onAnimationComplete={() => {
                  // Release lock when the last item of the CURRENT BATCH finishes animating
                  if (index === cards.length - 1) {
                    if (isLoaderInView && hasNextPage && !isFetchingNextPage) {
                      // Keep lock and immediately request the next page if the loader is still visible.
                      fetchNextPage()
                    } else {
                      setIsAnimating(false)
                    }
                  }
                }}
              >
                <div
                  onClick={() => onCardClick(s)}
                  className="group relative block aspect-[5/7] cursor-pointer overflow-hidden border border-white/5 bg-[#262626] shadow-lg transition-all duration-300 hover:-translate-y-1 hover:scale-[1.02] hover:shadow-2xl hover:ring-1 hover:ring-[#e3dccb]/30"
                  style={{ borderRadius: '4.5% / 3.21%' }}
                >
                  <CardImage
                    src={getCardImageUrl(s)}
                    alt={s.name}
                    loading="lazy"
                    className="h-full w-full object-cover"
                  />

                  {/* Similarity Badge */}
                  <div className="absolute top-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full border border-white/5 bg-[#171717]/90 px-3 py-1 shadow-lg backdrop-blur-md">
                    <div
                      className={cn(
                        'h-2 w-2 rounded-full',
                        s.similarity > 0.8
                          ? 'bg-emerald-500/80 shadow-[0_0_8px_rgba(16,185,129,0.4)]'
                          : 'bg-amber-500/80 shadow-[0_0_8px_rgba(245,158,11,0.4)]'
                      )}
                    />
                    <span className="text-xs font-bold text-[#f5f2eb]">
                      {(s.similarity * 100).toFixed(1)}%
                    </span>
                  </div>

                  {/* Hover Name Overlay */}
                  <div className="absolute inset-x-0 bottom-0 translate-y-full bg-gradient-to-t from-[#171717] via-[#171717]/90 to-transparent p-4 pt-12 transition-transform duration-300 group-hover:translate-y-0">
                    <p className="truncate text-center text-sm font-medium text-[#f5f2eb]">
                      {s.name}
                    </p>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Loading Indicator / Infinite Scroll Trigger */}
          <motion.div
            className="flex justify-center py-8"
            onViewportEnter={() => {
              setIsLoaderInView(true)
              startNextPageFetch()
            }}
            onViewportLeave={() => setIsLoaderInView(false)}
            viewport={{ margin: '200px' }} // Preload
          >
            {isFetchingNextPage && (
              <div className="flex items-center gap-2 text-[#737373]">
                <div
                  className="h-2 w-2 animate-bounce rounded-full bg-[#e3dccb]"
                  style={{ animationDelay: '0s' }}
                ></div>
                <div
                  className="h-2 w-2 animate-bounce rounded-full bg-[#e3dccb]"
                  style={{ animationDelay: '0.2s' }}
                ></div>
                <div
                  className="h-2 w-2 animate-bounce rounded-full bg-[#e3dccb]"
                  style={{ animationDelay: '0.4s' }}
                ></div>
              </div>
            )}
            {!isLoading && cards.length === 0 && noResultsMessage}
            {!hasNextPage && cards.length > 0 && (
              <span className="text-sm text-[#525252]">End of results</span>
            )}
          </motion.div>
        </>
      )}
    </div>
  )
}
