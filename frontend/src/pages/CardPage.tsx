import { useParams, Link } from 'react-router-dom';
import { useQuery, useInfiniteQuery } from '@tanstack/react-query';
import { getCard, getSimilarCards } from '../api';
import { ArrowLeft, SlidersHorizontal } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { CardOverlay } from '../components/CardOverlay';
import type { SimilarCard } from '../types';
import { getCardImageUrl } from '../utils';

export function CardPage() {
  const { id } = useParams<{ id: string }>();
  const loadMoreRef = useRef<HTMLDivElement>(null);
  const [selectedCard, setSelectedCard] = useState<SimilarCard | null>(null);

  // Reset selected card when ID changes (i.e. when navigating to a new main card)
  useEffect(() => {
    setSelectedCard(null);
  }, [id]);

  const { data: card, isLoading: cardLoading, error: cardError } = useQuery({
    queryKey: ['card', id],
    queryFn: () => getCard(id!),
    enabled: !!id,
  });

  const {
    data: similarData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: similarLoading
  } = useInfiniteQuery({
    queryKey: ['similar', id],
    queryFn: ({ pageParam = 0 }) => getSimilarCards(id!, pageParam, 24),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      // If we received fewer items than the limit (24), we're at the end
      return lastPage.length === 24 ? allPages.length * 24 : undefined;
    },
    enabled: !!id,
  });

  const similarCards = similarData?.pages.flatMap((page) => page) || [];

  // Intersection Observer for infinite scrolling
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      { threshold: 0.1 }
    );

    if (loadMoreRef.current) {
      observer.observe(loadMoreRef.current);
    }

    return () => {
      if (loadMoreRef.current) {
        observer.unobserve(loadMoreRef.current);
      }
    };
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Update document title when card is loaded
  useEffect(() => {
    if (card?.name) {
      document.title = `${card.name} - Oracle tutor`;
    }
  }, [card]);

  // Handle keyboard ESC to close overlay
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedCard(null);
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, []);

  if (cardLoading) return <div className="h-screen flex items-center justify-center text-[#f5f2eb]">Loading knowledge...</div>;
  if (cardError || !card) return <div className="h-screen flex items-center justify-center text-[#f5f2eb]">Card not found.</div>;

  // Resolve display properties for the main card
  // If the card has faces (DFC), prefer the first face for the main view if flattened props are missing
  const displayType = card.type_line || card.faces?.[0]?.type_line;
  const displayMana = card.mana_cost || card.faces?.[0]?.mana_cost;
  const displayOracle = card.oracle_text || card.faces?.[0]?.oracle_text;
  
  // Main card image usually defaults to front face
  const mainCardImageUrl = getCardImageUrl(card);

  return (
    <div className="h-screen w-full flex flex-col md:flex-row overflow-hidden bg-transparent">
      
      {/* Overlay Component */}
      {selectedCard && (
        <CardOverlay 
          card={selectedCard} 
          onClose={() => setSelectedCard(null)} 
        />
      )}

      {/* Sidebar - Selected Card Details */}
      <div className="w-full md:w-[380px] flex-shrink-0 h-full overflow-y-auto bg-[#f5f2eb] border-r border-[#e5e5e5] p-5 flex flex-col">
        <Link to="/" className="flex items-center gap-2 text-[#525252] mb-6 hover:text-[#1c1c1c] transition-colors">
          <ArrowLeft size={16} /> Back to Search
        </Link>

        {/* Card "Paper" Container */}
        <div className="bg-white rounded-xl p-5 shadow-lg border border-[#e5e5e5] text-[#1c1c1c]">
           {/* Card Image - Clickable to open overlay */}
          <div 
             className="relative aspect-[5/7] w-full mb-5 overflow-hidden bg-[#f0f0f0] shadow-lg ring-1 ring-black/5 cursor-pointer hover:ring-black/10 transition-all hover:scale-[1.02]" 
             style={{ borderRadius: '4.5% / 3.21%' }}
             onClick={() => setSelectedCard({ ...card, similarity: 1 } as SimilarCard)}
          >
             <img 
                src={mainCardImageUrl} 
                alt={card.name}
                className="w-full h-full object-cover"
              />
          </div>

          <h1 className="text-2xl font-bold mb-2 leading-tight text-[#1c1c1c]">{card.name}</h1>
          
          <div className="flex flex-col gap-3 mb-4">
             <div className="flex flex-col">
                <span className="text-xs uppercase tracking-wider font-semibold text-[#737373]">Type</span>
                <span className="font-medium">{displayType}</span>
             </div>
             <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col">
                    <span className="text-xs uppercase tracking-wider font-semibold text-[#737373]">Mana</span>
                    <span className="font-medium">{displayMana || 'None'}</span>
                </div>
                 <div className="flex flex-col">
                    <span className="text-xs uppercase tracking-wider font-semibold text-[#737373]">Rank</span>
                    <span className="font-medium">#{card.edhrec_rank}</span>
                </div>
             </div>
          </div>

          <div className="pt-4 border-t border-[#e5e5e5]">
             <span className="text-xs uppercase tracking-wider font-semibold text-[#737373] block mb-2">Oracle Text</span>
             <p className="whitespace-pre-wrap text-sm leading-relaxed text-[#404040]">
               {displayOracle}
             </p>
          </div>
        </div>
      </div>

      {/* Main Content - Similar Cards Grid */}
      <div className="flex-1 h-full overflow-y-auto bg-transparent relative scroll-smooth">
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
          {similarCards.map((s) => (
            <div 
              key={s.id} 
              onClick={() => setSelectedCard(s)}
              className="group relative aspect-[5/7] overflow-hidden bg-[#262626] shadow-lg hover:-translate-y-1 hover:shadow-2xl hover:ring-1 hover:ring-[#e3dccb]/30 hover:scale-[1.02] border border-white/5 transition-all duration-300 block cursor-pointer" 
              style={{ borderRadius: '4.5% / 3.21%' }}
            >
               <img 
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
          ))}
        </div>

        {/* Loading Indicator / Infinite Scroll Trigger */}
        <div ref={loadMoreRef} className="flex justify-center py-8">
          {(isFetchingNextPage || similarLoading) && (
             <div className="flex items-center gap-2 text-[#737373]">
                <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0s' }}></div>
                <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
             </div>
          )}
          {!hasNextPage && similarCards.length > 0 && (
            <span className="text-[#525252] text-sm">End of results</span>
          )}
        </div>
      </div>
    </div>
  );
}
