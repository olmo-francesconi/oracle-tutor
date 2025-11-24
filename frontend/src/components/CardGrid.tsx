import { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';
import { SlidersHorizontal } from 'lucide-react';
import { CardImage } from './CardImage';
import { getCardImageUrl } from '../utils';
import type { SimilarCard } from '../types';

interface CardGridProps {
  cards: SimilarCard[];
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean;
  fetchNextPage: () => void;
  onCardClick: (card: SimilarCard) => void;
  noResultsMessage?: React.ReactNode;
  searchQuery?: string;
}

export function CardGrid({ 
  cards, 
  isLoading, 
  isFetchingNextPage, 
  hasNextPage, 
  fetchNextPage, 
  onCardClick,
  noResultsMessage,
  searchQuery
}: CardGridProps) {
  const [isAnimating, setIsAnimating] = useState(false);
  const [isLoaderInView, setIsLoaderInView] = useState(false);
  const prevCardsLength = useRef(cards.length);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Scroll to top when search query changes
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, [searchQuery]);

  // Lock infinite scroll when we receive new cards until they animate in
  useEffect(() => {
    // If we have more cards than before, lock animation
    if (cards.length > prevCardsLength.current) {
      setIsAnimating(true);
    }
    prevCardsLength.current = cards.length;
  }, [cards.length]);

  // Trigger infinite scroll
  useEffect(() => {
    if (!isAnimating && isLoaderInView && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [isAnimating, isLoaderInView, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Initial loading state is now handled inside the main return to preserve the scroll container ref
  const showInitialLoader = isLoading && cards.length === 0;

  return (
    <div ref={scrollContainerRef} className="flex-1 h-full overflow-y-auto bg-transparent relative scroll-smooth">
      {showInitialLoader ? (
        <div className="flex items-center justify-center h-full">
          <div className="flex items-center gap-2 text-[#737373]">
            <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0s' }}></div>
            <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
            <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
          </div>
        </div>
      ) : (
        <>
          {/* Sticky Header with Blur Effect */}
          <div className="sticky top-0 z-30 flex items-center justify-end px-6 py-4 bg-[#1c1c1c]/70 backdrop-blur-xl border-b border-white/5 transition-all duration-300 supports-[backdrop-filter]:bg-[#1c1c1c]/60">
            <div className="flex items-center gap-3">
              {/* Placeholder for future filter controls */}
              <button className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#262626] border border-white/5 text-[#f5f2eb] hover:bg-[#333] hover:border-[#e3dccb]/30 transition-all text-sm font-medium cursor-pointer shadow-sm active:scale-95">
                <SlidersHorizontal size={16} />
                <span>Filters</span>
              </button>
            </div>
          </div>
          
          {/* Grid with larger cards (fewer columns) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6 p-6 pt-6 pb-10">
            {cards.map((s, index) => (
              <motion.div 
                key={s.id} 
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ 
                  duration: 0.3, 
                  delay: (index % 60) * 0.05, 
                  ease: "easeOut" 
                }}
                onAnimationComplete={() => {
                  // Release lock when the last item of the CURRENT BATCH finishes animating
                  if (index === cards.length - 1) {
                    setIsAnimating(false);
                  }
                }}
              >
                <div
                  onClick={() => onCardClick(s)}
                  className="group relative aspect-[5/7] overflow-hidden bg-[#262626] shadow-lg hover:-translate-y-1 hover:shadow-2xl hover:ring-1 hover:ring-[#e3dccb]/30 hover:scale-[1.02] border border-white/5 transition-all duration-300 block cursor-pointer" 
                  style={{ borderRadius: '4.5% / 3.21%' }}
                >
                <CardImage 
                  src={getCardImageUrl(s)} 
                  alt={s.name}
                  loading="lazy"
                  className="w-full h-full object-cover"
                />
                
                {/* Similarity Badge */}
                <div className="absolute top-3 left-1/2 -translate-x-1/2 bg-[#171717]/90 backdrop-blur-md border border-white/5 rounded-full px-3 py-1 flex items-center gap-2 shadow-lg z-10">
                  <div className={`w-2 h-2 rounded-full ${s.similarity > 0.8 ? 'bg-emerald-500/80 shadow-[0_0_8px_rgba(16,185,129,0.4)]' : 'bg-amber-500/80 shadow-[0_0_8px_rgba(245,158,11,0.4)]'}`}></div>
                  <span className="text-xs font-bold text-[#f5f2eb]">{(s.similarity * 100).toFixed(1)}%</span>
                </div>

                {/* Hover Name Overlay */}
                <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-[#171717] via-[#171717]/90 to-transparent p-4 pt-12 translate-y-full group-hover:translate-y-0 transition-transform duration-300">
                  <p className="text-[#f5f2eb] text-center font-medium text-sm truncate">{s.name}</p>
                </div>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Loading Indicator / Infinite Scroll Trigger */}
          <motion.div 
            className="flex justify-center py-8"
            onViewportEnter={() => setIsLoaderInView(true)}
            onViewportLeave={() => setIsLoaderInView(false)}
            viewport={{ margin: "200px" }} // Preload
          >
            {(isFetchingNextPage) && (
              <div className="flex items-center gap-2 text-[#737373]">
                  <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0s' }}></div>
                  <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                  <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
              </div>
            )}
            {!isLoading && cards.length === 0 && noResultsMessage}
            {!hasNextPage && cards.length > 0 && (
              <span className="text-[#525252] text-sm">End of results</span>
            )}
          </motion.div>
        </>
      )}
    </div>
  );
}
