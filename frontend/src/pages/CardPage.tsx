import { useParams, Link } from 'react-router-dom';
import { useQuery, useInfiniteQuery } from '@tanstack/react-query';
import { getCard, getSimilarCards } from '../api';
import { ArrowLeft } from '@phosphor-icons/react';
import { useEffect, useState, useMemo } from 'react';
import { CardOverlay } from '../components/CardOverlay';
import { CardImage } from '../components/CardImage';
import { CardGrid } from '../components/CardGrid';
import { DeveloperLinks } from '../components/DeveloperLinks';
import type { SimilarCard } from '../types';
import { getCardImageUrl } from '../utils';

export function CardPage() {
  const { id } = useParams<{ id: string }>();
  const [selected, setSelected] = useState<{ routeId: string; card: SimilarCard } | null>(null);
  const selectedCard = selected?.routeId === (id ?? '') ? selected.card : null;

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
    queryFn: ({ pageParam = 0 }) => {
      return getSimilarCards(id!, pageParam, 60);
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      // If we received fewer items than the limit (60), we're at the end
      return lastPage.length === 60 ? allPages.length * 60 : undefined;
    },
    enabled: !!id,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
  });

  const similarCards = useMemo(() => {
    return similarData?.pages.flatMap((page) => page) || [];
  }, [similarData]);

  // Update document title when card is loaded
  useEffect(() => {
    if (card?.name) {
      document.title = `${card.name} - Oracle tutor`;
    }
  }, [card]);

  // Handle keyboard ESC to close overlay
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null);
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
          onClose={() => setSelected(null)} 
        />
      )}

      {/* Sidebar - Selected Card Details */}
      <div className="w-full md:w-[380px] flex-shrink-0 h-full overflow-y-auto bg-[#f5f2eb] border-r border-[#e5e5e5] p-5 flex flex-col">
        <Link to="/" className="flex items-center gap-2 text-[#525252] mb-6 hover:text-[#1c1c1c] transition-colors">
          <ArrowLeft className="h-4 w-4" /> Back to Search
        </Link>

        {/* Card "Paper" Container */}
        <div className="bg-white rounded-xl p-5 shadow-lg border border-[#e5e5e5] text-[#1c1c1c]">
           {/* Card Image - Clickable to open overlay */}
          <div 
             className="relative aspect-[5/7] w-full mb-5 overflow-hidden bg-[#f0f0f0] shadow-lg ring-1 ring-black/5 cursor-pointer hover:ring-black/10 transition-all hover:scale-[1.02]" 
             style={{ borderRadius: '4.5% / 3.21%' }}
             onClick={() => setSelected({ routeId: id ?? '', card: { ...card, similarity: 1 } as SimilarCard })}
          >
             <CardImage 
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
      />
    </div>
  );
}
